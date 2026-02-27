import pandas as pd
from src.preprocessing.schema import (
    apply_gl_schema,
    apply_subledger_schema,
    apply_coa_schema,
    apply_ground_truth_schema,
)

gl_df = pd.read_csv("data/raw/GL.csv")
sub_df = pd.read_csv("data/raw/Subledger.csv")
coa_df = pd.read_csv("data/raw/Chart_of_Accounts.csv")
gt_df = pd.read_csv("data/raw/Ground_Truth_Exceptions.csv")

gl_df = apply_gl_schema(gl_df)
sub_df = apply_subledger_schema(sub_df)
coa_df = apply_coa_schema(coa_df)
gt_df = apply_ground_truth_schema(gt_df)

print("All schemas validated successfully.")