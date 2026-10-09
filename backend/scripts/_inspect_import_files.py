# -*- coding: utf-8 -*-
"""临时检查 2：1482 文件的岗位分布与字段内容。跑完即删。"""
import pandas as pd

p = "/app/backend/uploads/import/1482_比赛数据_Sheet1_计算机岗位_Sheet1.xlsx"
df = pd.read_excel(p, sheet_name=0, header=0)
print("total rows:", len(df))
print("distinct 岗位名称:", df["岗位名称"].nunique())
print(df["岗位名称"].value_counts().head(15).to_string())
print("\n空值统计:")
print(df.isna().sum().to_string())
print("\n薪资范围 前8 样例:")
print(df["薪资范围"].dropna().head(8).tolist())
print("\n岗位来源地址 前3:")
print(df["岗位来源地址"].dropna().head(3).tolist())
print("\n岗位详情 是否有含公司线索的样例（公司/有限公司/集团）:")
mask = df["岗位详情"].astype(str).str.contains("公司|有限|集团", na=False)
print("含公司字样行数:", mask.sum())
if mask.any():
    print(df.loc[mask, "岗位详情"].head(2).tolist())
