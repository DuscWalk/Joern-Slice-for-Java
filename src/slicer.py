import subprocess
import tempfile
from pathlib import Path
import re
import json
import os
from settings import JOERN_BIN, JOERN_WORKSPACE, CPG_ROOT, SOURCE_ROOT, project_name



def run_joern_query(query: str, print_info: bool = False) -> tuple[str, str]:
    """在 Joern 中执行 Scala 查询脚本，通过环境变量设置工作空间，返回 (stdout, stderr)"""
    with tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False) as f:
        f.write(query)
        script_path = f.name

    try:
        env = os.environ.copy()
        env["JOERN_WORKSPACE"] = JOERN_WORKSPACE

        result = subprocess.run(
            [JOERN_BIN, "--script", script_path],
            capture_output=True,
            text=True,
            timeout=180,
            env=env
        )

        if print_info:
            if result.stdout.strip():
                print(f"[run_joern_query] stdout:\n{result.stdout.strip()}")
            if result.stderr.strip():
                print(f"[run_joern_query] stderr:\n{result.stderr.strip()}")

        return result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        print("[run_joern_query] Timeout expired")
        return "", ""
    finally:
        Path(script_path).unlink(missing_ok=True)

def ensure_project(cpg_file: str) -> str:
    """导入 CPG 并返回 Joern workspace 中的 project 名"""
    cpg_path = Path(cpg_file)
    project_name = cpg_path.name

    # Joern 导入成功后会在 workspace 下生成同名目录，用它判断是否需要重复导入。
    workspace_project_path = Path(JOERN_WORKSPACE) / project_name

    print(f"[ensure_project] 使用 project 名: {project_name}")
    if not workspace_project_path.exists():
        import_query = f'importCpg("{cpg_file}")'
        try:
            env = os.environ.copy()
            env["JOERN_WORKSPACE"] = JOERN_WORKSPACE
            with tempfile.NamedTemporaryFile("w", suffix=".sc", delete=False) as f:
                f.write(import_query)
                script_path = f.name
            subprocess.run(
                [JOERN_BIN, "--script", script_path],
                capture_output=True,
                text=True,
                timeout=180,
                env=env
            )
            Path(script_path).unlink(missing_ok=True)
        except subprocess.TimeoutExpired:
            print(f"[ensure_project] Import timeout, skip: {cpg_file}")
            return None
    return project_name

def build_query(file_path: str, line: int, project_name: str) -> str:
    """
    构造 Joern 查询脚本（Scala 代码）。
    主要步骤：
      1. 打开指定项目，获取 CPG。
      2. 精确匹配目标文件。
      3. 在文件内查找指定行号的 AST 节点（若没有则找附近 ±5 行的节点）。
      4. 对每个起点进行双向数据流/控制流依赖收集，并跨越方法调用（最多 8 层深度）。
      5. 输出所有相关节点的 "文件:行号"。
    """
    # Joern 内部统一使用 POSIX 风格路径，先做一次归一化避免匹配失败。
    file_path_posix = file_path.replace("\\", "/")

    # 这里返回的是完整 Scala 脚本字符串，会被 run_joern_query 临时写入 .sc 后执行。
    query = f"""
import io.shiftleft.codepropertygraph.generated.nodes._
import io.shiftleft.semanticcpg.language._

// 打开项目，获取 CPG
val projectOpt = open("{project_name}")
val cpg: Cpg = projectOpt.flatMap(_.cpg).getOrElse {{
    println("FAILED_TO_LOAD_CPG")
    sys.exit(0)
}}

val lineNum = {line}
val targetPath = "{file_path_posix}"

// 精确匹配文件
println(s"[DEBUG] Exact matching: $targetPath")
val exactFile = cpg.file.nameExact(targetPath).headOption
if (exactFile.isEmpty) {{
    println("NO_NODE_FOUND")
    sys.exit(0)
}}

val targetFile = exactFile.get
println(s"[DEBUG] Exact file found: ${{targetFile.name}}")

// 查找目标行号的 AST 节点
var nodes = targetFile.method.ast.filter(_.lineNumber.contains(lineNum)).l
println(s"[DEBUG] Found ${{nodes.size}} nodes at exact line $lineNum")

// 若没有精确匹配，则找附近 ±5 行内的节点，按与目标行距离排序
if (nodes.isEmpty) {{
    println(s"[DEBUG] No nodes at exact line, searching nearby lines...")
    val nearbyNodes = targetFile.method.ast
        .filter(_.lineNumber.isDefined)
        .filter(n => math.abs(n.lineNumber.get - lineNum) <= 5)
        .l
        .sortBy(_.lineNumber.get)
    println(s"[DEBUG] Found ${{nearbyNodes.size}} nodes within ±5 lines")
    
    if (nearbyNodes.isEmpty) {{
        println("NO_NODE_FOUND")
        sys.exit(0)
    }}
    
    // 使用所有附近节点作为起点
    nodes = nearbyNodes
}}

/**
 * 双向依赖收集函数。
 * @param startNodes 起始节点列表
 * @param depth      最大遍历深度
 * @param forward    方向：true 为前向，false 为后向
 * @return 所有依赖节点（不含起始节点）
 */
def collectDeps(startNodes: List[StoredNode], depth: Int, forward: Boolean): Set[StoredNode] = {{
    var frontier = startNodes
    var visited = startNodes.toSet
    var d = 0
    while (frontier.nonEmpty && d < depth) {{
        val next = frontier.flatMap {{ n =>
            // 数据依赖边（REACHING_DEF）和控制依赖边（CDG）
            val dataEdges = if (forward) n.out("REACHING_DEF").l else n.in("REACHING_DEF").l
            val controlEdges = if (forward) n.out("CDG").l else n.in("CDG").l
            val deps = (dataEdges ++ controlEdges).map(_.asInstanceOf[StoredNode])
            
            // 跨方法：如果当前节点是调用，获取被调用方法的 AST 节点（限制数量，避免爆炸）
            val crossMethodNodes = n match {{
                case call: Call =>
                    val callees = call.out("CALL").l.map(_.asInstanceOf[Method])
                    callees.flatMap {{ m =>
                        m.ast.l
                          .filter(_.lineNumber.isDefined)          // 只保留有行号的节点
                          .sortBy(_.lineNumber.get)                // 按行号排序
                          .take(20)                                 // 每个方法最多取20个节点
                          .map(_.asInstanceOf[StoredNode])
                    }}
                case _ => List()
            }}
            
            deps ++ crossMethodNodes
        }}.filterNot(visited.contains).distinct
        visited = visited ++ next
        frontier = next
        d += 1
    }}
    visited -- startNodes.toSet
}}

// 对每个起点收集双向切片（深度 8），并合并所有节点（含起点）
val allSliceNodes = nodes.flatMap {{ startNode =>
    val backward = collectDeps(List(startNode), 8, forward = false)
    val forward  = collectDeps(List(startNode), 8, forward = true)
    backward ++ forward + startNode
}}.toSet

println(s"[DEBUG] Total slice nodes from all starts: ${{allSliceNodes.size}}")

val sorted = allSliceNodes.filter(_.location.lineNumber.isDefined)
                           .toList
                           .sortBy(_.location.lineNumber.get)

sorted.foreach {{ n =>
    val loc = n.location
    // 不再限制文件名，允许输出所有文件中的节点
    println(s"${{loc.filename}}:${{loc.lineNumber.get}}")
}}
"""
    return query

def extract(reports: list[dict], project_cpg_file: str, source_root: str, print_info: bool = False) -> list[dict]:
    """
    主提取函数：
      1. 确保 CPG 已导入。
      2. 为每个报告生成查询并执行，将输出解析为代码行上下文。
      3. 将结果存入报告的 'joern_context' 字段。
      4. 同时将 Python 端的提示信息和 Scala 的输出均写入日志文件。
    """
    if not os.path.exists(project_cpg_file):
        raise FileNotFoundError(f"项目 CPG 文件不存在: {project_cpg_file}")

    project_name = ensure_project(str(project_cpg_file))
    if project_name is None:
        raise RuntimeError(f"无法导入 CPG 文件: {project_cpg_file}")

    # 创建日志目录
    log_dir = Path(source_root) / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{project_name}.log"
    # 清空日志文件（每次运行只保留本次日志）
    with open(log_file, "w", encoding="utf-8") as f:
        pass  # 打开并立即关闭，清空文件内容

    project_dir = Path(source_root) / "project" / project_name.replace(".cpg", "")

    for idx, issue in enumerate(reports):
        # Python 端日志辅助函数
        def log_py(msg: str):
            if print_info:
                print(msg)
            with open(log_file, "a", encoding="utf-8") as log_f:
                log_f.write(f"[PY] {msg}\n")

        log_py(f"处理报告 {idx+1}/{len(reports)}: {issue.get('file', '?')}:{issue.get('line', '?')}")

        file_path = issue.get("file")
        line = issue.get("line")
        if not file_path or not line:
            log_py("  缺少 file 或 line，跳过")
            issue["joern_context"] = []
            continue

        # 仅处理 Java 文件（CPG 中只包含 Java 源码）
        if not file_path.endswith('.java'):
            log_py(f"  非 Java 文件，跳过")
            issue["joern_context"] = []
            continue

        # 检查源文件是否存在（辅助调试）
        full_source_path = project_dir / file_path.replace("\\", "/")
        if not full_source_path.exists():
            log_py(f"  源文件不存在: {full_source_path}")
            # # DEBUG：打印路径的 repr 以检查隐藏字符
            # log_py(f"  路径 repr: {repr(str(full_source_path))}")
            # # 检查父目录是否存在
            # parent = full_source_path.parent
            # log_py(f"  父目录: {parent}")
            # log_py(f"  父目录 exists? {parent.exists()}")
            # if parent.exists():
            #     # 列出父目录下所有文件，用于对比
            #     log_py(f"  父目录内容：")
            #     for child in parent.iterdir():
            #         log_py(f"    - {child.name}")
            # else:
            #     log_py(f"  父目录不存在")
            issue["joern_context"] = []
            continue

        query = build_query(file_path, line, project_name)
        stdout, stderr = run_joern_query(query, print_info=print_info)

        # 将调试信息写入日志文件（Scala 端）
        with open(log_file, "a", encoding="utf-8") as log_f:
            log_f.write(f"--- {file_path}:{line} ---\n")
            if stdout:
                log_f.write("STDOUT:\n")
                log_f.write(stdout)
                log_f.write("\n")
            if stderr:
                log_f.write("STDERR:\n")
                log_f.write(stderr)
                log_f.write("\n")

        context_lines = []
        if stdout and "NO_NODE_FOUND" not in stdout and "FAILED_TO_LOAD_CPG" not in stdout:
            # Scala 脚本会输出 "文件路径:行号"，这里逐行解析并回填对应源码文本。
            for line_text in stdout.splitlines():
                line_text = line_text.strip()
                if not line_text:
                    continue
                match = re.match(r"^(.+):(\d+)$", line_text)
                if match:
                    f, l = match.groups()
                    full_path = project_dir / f
                    code = ""
                    try:
                        with open(full_path, 'r', encoding='utf-8') as src_file:
                            lines = src_file.readlines()
                            if 1 <= int(l) <= len(lines):
                                code = lines[int(l)-1].rstrip('\n')
                    except Exception as e:
                        log_py(f"  读取文件失败: {full_path} - {e}")
                    context_lines.append({
                        "file": f,
                        "line": int(l),
                        "code": code
                    })

        seen = set()
        unique_lines = []   
        for ctx in context_lines:
            key = (ctx["file"], ctx["line"])
            if key not in seen:
                seen.add(key)
                unique_lines.append(ctx)

        issue["joern_context"] = unique_lines

        log_py(f"  提取到 {len(unique_lines)} 行上下文")

    return reports

if __name__ == "__main__":
    project_cpg = Path(CPG_ROOT) / f"{project_name}.cpg"
    reports_path = Path(os.path.join(SOURCE_ROOT, "jsons", f"{project_name}.json"))
    output_path = Path(os.path.join(SOURCE_ROOT, "output", f"{project_name}.json"))
    source_root = SOURCE_ROOT

    with open(reports_path, "r") as f:
        reports = json.load(f)

    # 处理前 N 条，便于测试
    # N = 200   
    # reports = reports[:N]

    result = extract(reports, project_cpg, source_root, print_info=True)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)