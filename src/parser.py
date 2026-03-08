import pandas as pd
import json
import os
from pathlib import Path

xlsx_dir = Path("/home/duscwalk/javatest/dataset/horusec")

json_dir = Path("/home/duscwalk/javatest/jsons")

for root, dirs, files in os.walk(xlsx_dir):
    for file in files:
        # print('文件:', os.path.join(root, file))
        if not file.endswith("xlsx"):
            continue
        xlsx_file = Path(os.path.join(root, file))
        df = pd.read_excel(xlsx_file)
        json_str = df.to_json(orient='records', force_ascii=False)
        data = df.to_dict(orient='records')
        with open(os.path.join(json_dir, Path(file).with_suffix(".json")), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# # 读取Excel文件
# df = pd.read_excel('systemds-2.1.0-rc3.xlsx', sheet_name='Sheet1')

# # 转换为JSON字符串（每行一个对象）
# json_str = df.to_json(orient='records', force_ascii=False)

# # 如果需要保存到文件
# with open('output.json', 'w', encoding='utf-8') as f:
#     f.write(json_str)

# # 如果需要格式化的JSON（带缩进）
# # 先解析为Python对象再写入
# data = df.to_dict(orient='records')
# with open('output_pretty.json', 'w', encoding='utf-8') as f:
#     json.dump(data, f, ensure_ascii=False, indent=2)