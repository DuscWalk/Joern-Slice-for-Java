import subprocess
import tempfile
from pathlib import Path
import re
import json
import os

# 全局配置
JOERN_BIN = "joern"
CPG_ROOT = "/home/duscwalk/javatest/javaCPGs"
JOERN_WORKSPACE = "/home/duscwalk/javatest/workspace"
SOURCE_ROOT = "/home/duscwalk/javatest"

def run_joern_query(query: str, print_info: bool = False) -> str:
    """在 Joern 中执行 Scala 查询脚本，通过环境变量设置工作空间"""
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

        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("[run_joern_query] Timeout expired")
        return ""
    finally:
        Path(script_path).unlink(missing_ok=True)

def ensure_project(cpg_file: str) -> str:
    """导入 CPG 并返回 Joern workspace 中的 project 名"""
    cpg_path = Path(cpg_file)
    project_name = cpg_path.name

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
    file_path_posix = file_path.replace("\\", "/")

    query = f"""
import io.shiftleft.codepropertygraph.generated.nodes._
import io.shiftleft.semanticcpg.language._

val projectOpt = open("{project_name}")
val cpg: Cpg = projectOpt.flatMap(_.cpg).getOrElse {{
    println("FAILED_TO_LOAD_CPG")
    sys.exit(0)
}}

val lineNum = {line}
val targetPath = "{file_path_posix}"

println(s"[DEBUG] Exact matching: $targetPath")
val exactFile = cpg.file.nameExact(targetPath).headOption
if (exactFile.isEmpty) {{
    println("NO_NODE_FOUND")
    sys.exit(0)
}}

val targetFile = exactFile.get
println(s"[DEBUG] Exact file found: ${{targetFile.name}}")

var nodes = targetFile.method.ast.filter(_.lineNumber.contains(lineNum)).l
println(s"[DEBUG] Found ${{nodes.size}} nodes at exact line $lineNum")

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

def collectDeps(startNodes: List[StoredNode], depth: Int, forward: Boolean): Set[StoredNode] = {{
    var frontier = startNodes
    var visited = startNodes.toSet
    var d = 0
    while (frontier.nonEmpty && d < depth) {{
        val next = frontier.flatMap {{ n =>
            // 数据依赖和控制依赖
            val dataEdges = if (forward) n.out("REACHING_DEF").l else n.in("REACHING_DEF").l
            val controlEdges = if (forward) n.out("CDG").l else n.in("CDG").l
            val deps = (dataEdges ++ controlEdges).map(_.asInstanceOf[StoredNode])
            
            // 跨方法：如果当前节点是调用，获取被调用方法的所有 AST 节点
            val crossMethodNodes = n match {{
                case call: Call =>
                    // 通过 CALL 边找到被调用的方法
                    val callees = call.out("CALL").l.map(_.asInstanceOf[Method])
                    callees.flatMap(_.ast.l.map(_.asInstanceOf[StoredNode]))
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

// 对每个起点收集切片并合并
val allSliceNodes = nodes.flatMap {{ startNode =>
    val backward = collectDeps(List(startNode), 15, forward = false)
    val forward  = collectDeps(List(startNode), 15, forward = true)
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
    if not os.path.exists(project_cpg_file):
        raise FileNotFoundError(f"项目 CPG 文件不存在: {project_cpg_file}")

    project_name = ensure_project(str(project_cpg_file))
    if project_name is None:
        raise RuntimeError(f"无法导入 CPG 文件: {project_cpg_file}")

    # 项目源代码根目录（根据您的 tree 结构）
    project_dir = Path(source_root) / "project" / project_name.replace(".cpg", "")

    for idx, issue in enumerate(reports):
        if print_info:
            print(f"处理报告 {idx+1}/{len(reports)}: {issue.get('file', '?')}:{issue.get('line', '?')}")

        file_path = issue.get("file")
        line = issue.get("line")
        if not file_path or not line:
            if print_info:
                print("  缺少 file 或 line，跳过")
            issue["joern_context"] = []
            continue

        # 仅处理 Java 文件（CPG 中只包含 Java 源码）
        if not file_path.endswith('.java'):
            if print_info:
                print(f"  非 Java 文件，跳过")
            issue["joern_context"] = []
            continue

        # 检查源文件是否存在（辅助调试）
        full_source_path = project_dir / file_path.replace("\\", "/")
        if not full_source_path.exists():
            if print_info:
                print(f"  源文件不存在: {full_source_path}，跳过")
            issue["joern_context"] = []
            continue

        query = build_query(file_path, line, project_name)
        output = run_joern_query(query, print_info=print_info)

        context_lines = []
        if output and "NO_NODE_FOUND" not in output and "FAILED_TO_LOAD_CPG" not in output:
            for line_text in output.splitlines():
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
                        if print_info:
                            print(f"  读取文件失败: {full_path} - {e}")
                    context_lines.append({
                        "file": f,
                        "line": int(l),
                        "code": code
                    })

        seen = set()
        unique_lines = []
        for ctx in sorted(context_lines, key=lambda x: x["line"]):
            key = (ctx["file"], ctx["line"])
            if key not in seen:
                seen.add(key)
                unique_lines.append(ctx)

        issue["joern_context"] = unique_lines

        if print_info:
            print(f"  提取到 {len(unique_lines)} 行上下文")

    return reports

if __name__ == "__main__":
    project_name = "systemds-2.2.1-rc3"
    project_cpg = Path(CPG_ROOT) / f"{project_name}.cpg"
    reports_path = Path("/home/duscwalk/javatest/jsons") / f"{project_name}.json"
    output_path = Path("/home/duscwalk/javatest/output") / f"{project_name}.json"
    source_root = "/home/duscwalk/javatest"

    with open(reports_path, "r") as f:
        reports = json.load(f)

    # # 处理前 N 条，便于测试
    # N = 3
    # reports = reports[:N]

    result = extract(reports, project_cpg, source_root, print_info=True)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)