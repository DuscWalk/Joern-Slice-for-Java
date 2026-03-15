# Joern-Slice-for-Java

## 项目结构
```
.
├── README.md                          # 本文档
├── dataset                             # 存放原始警告数据（Excel）
│   └── horusec
│       ├── systemds-2.1.0-rc3.csv
│       ├── systemds-2.1.0-rc3.xlsx
│       └── systemds-2.2.1-rc3.xlsx
├── javaCPGs                             # 存放生成的 CPG 文件
│   ├── systemds-2.1.0-rc3.cpg
│   └── systemds-2.2.1-rc3.cpg
├── jsons                                 # 存放处理后的警告 JSON 文件（由 parser 生成或用户直接提供）
│   ├── systemds-2.1.0-rc3.json
│   └── systemds-2.2.1-rc3.json
├── logs                                  # 切片过程中产生的日志
│   ├── systemds-2.1.0-rc3.cpg.log
│   └── systemds-2.2.1-rc3.cpg.log
├── output                                # 切片结果输出目录
│   ├── systemds-2.1.0-rc3.json
│   └── systemds-2.2.1-rc3.json
├── project                               # 存放待分析的项目源代码（每个版本一个子目录）
│   ├── systemds-2.1.0-rc3
│   └── systemds-2.2.1-rc3
├── requirements.txt                      # Python 依赖列表
└── src                                   # 源代码目录
    ├── makeCPG                           # 生成 CPG 的相关脚本
    │   ├── CPGcommands.txt                # 已生成的命令示例
    │   └── runCPGcommands.sh              # 批量执行命令的脚本
    ├── parser.py                          # 解析 xlsx 警告文件 → json
    ├── settings.py                        # 配置文件
    ├── slicer.py                          # 切片主程序
    └── workspace                          # Joern 工作空间（自动生成，可忽略）
        ├── systemds-2.1.0-rc3.cpg
        ├── systemds-2.2.1-rc3.cpg
        └── workspace
```



## 依赖安装

### 1 Python 环境

新建环境，运行 ``` pip install -r requirements.txt ```

### 2 Joern 安装

> 参考 https://github.com/joernio/joern

```
wget https://github.com/joernio/joern/releases/latest/download/joern-install.sh
chmod +x ./joern-install.sh
sudo ./joern-install.sh

joern

     ██╗ ██████╗ ███████╗██████╗ ███╗   ██╗
     ██║██╔═══██╗██╔════╝██╔══██╗████╗  ██║
     ██║██║   ██║█████╗  ██████╔╝██╔██╗ ██║
██   ██║██║   ██║██╔══╝  ██╔══██╗██║╚██╗██║
╚█████╔╝╚██████╔╝███████╗██║  ██║██║ ╚████║
 ╚════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝
Version: 2.0.1
Type `help` to begin

joern>
```
出现以上交互式界面，表示 Joern 安装成功。

输入 ```exit``` 可退出交互式界面。

### 项目运行

#### 一、准备工作

1. 将项目源代码放入 project/ 下

2. 若现有警告为 excel 表格，则将文件放到 dataset/ 下；若为 json 文件，则直接放到 jsons/ 下

3. 将 src/settings.py 中的 ```xlsx_dir``` 改为存放 xlsx 警告的目录路径（默认为 javatest/dataset/horusec/ ）

4. 将 src/settings.py 中的 ```json_dir``` 改为存放 json 警告的目录路径（默认为 javatest/jsons/ ）

#### 二、解析 xlsx 文件

> 若现有警告均为 json 文件，则可跳过此步

通过在根目录下执行 ```python src/parser.py``` 或在 src/ 目录下执行 ```python parser.py```，可将 dataset/ 目录下所有 xlsx 文件转成 json 文件，并存入 javatest/jsons 目录下

#### 三、生成项目 CPG

通过在命令行中输入 ```joern-parse <javatest项目路径>/project/<项目名称> --language JAVASRC --output /<javatest项目路径>/javaCPGs/<项目名称>.cpg``` ，生成项目的 CPG 并存入 javatest/javaCPGs/ 目录下。具体命令可参考 javatest/src/makeCPG/CPGcommands.txt 中的已有命令

> 批处理方案：用 Python 脚本（本项目未提供）为多个项目生成以上命令，存入 javatest/src/makeCPG/CPGcommands.txt 中，再在 javatest/src/makeCPG/ 目录下执行 ```./runCPGcommands.sh``` ，可依次执行 CPGcommands.txt 中的每条命令，生成多个 CPG。

#### 四、利用 CPG ，对 JSON 中的警告做程序切片

1. 将 src/settings.py 中的 ```project_name``` 替换为实际的项目名称（因为单次解析时间较长，暂时没有做批处理的功能，每次只解析 1 个项目） 

2. 在根目录下运行 ```python src/slicer.py``` 或在 src/ 目录下运行 ```python slicer.py```，等待较长时间（数个小时）之后，在 javatest/output/ 下生成带切片的 json 警告文件，在 javatest/logs/ 下生成本次切片的日志

> 注：日志仅对本次运行做记录，若对同一项目（同一版本）做多次切片，则仅会保留最后一次的日志。

> 因 CPG 较大，切片时对 CPU 及内存需求大，请运行时不要在后台同时开启过多程序。

> src/slicer.py 中的主要函数为 `extract()`，其中参数 `print_info` 默认为 `True`，可将日志打印到控制台，以此观察切片进度
