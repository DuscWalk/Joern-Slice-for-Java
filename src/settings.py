from pathlib import Path
import os

SOURCE_ROOT = "/home/duscwalk/javatest"


# parser.py 配置
xlsx_dir = Path(
    os.path.join(
        SOURCE_ROOT, 
        "dataset/horusec"
        )
    )

json_dir = Path(
    os.path.join(
        SOURCE_ROOT, 
        "jsons"
        )
    )


# slicer.py 配置
JOERN_BIN = "joern"
CPG_ROOT = os.path.join(
    SOURCE_ROOT,
    "javaCPGs"
)
JOERN_WORKSPACE = os.path.join(
    SOURCE_ROOT,
    "workspace"
)

project_name = "systemds-2.1.0-rc3"  # 替换为实际项目名