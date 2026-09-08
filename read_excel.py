import pandas as pd

# 读取Excel文件
file_path = '/Users/alston/Documents/LuxAI/station-camera-dri/在职离职信息-HWTE 5678.xlsx'
df = pd.read_excel(file_path)

# 显示前5行数据（包括标题行）
print('=' * 80)
print('文件读取成功！共 {} 行 x {} 列'.format(len(df), len(df.columns)))
print('=' * 80)

# 打印标题行信息
print()
print('【标题行内容及列索引】')
print('-' * 60)
for idx, col in enumerate(df.columns):
    print('  列索引 {}: {}'.format(idx, col))

print()
print('=' * 80)
print('【前5行数据预览】')
print('=' * 80)

# 打印前5行数据，显示每个值的列索引
for row_num, (idx, row) in enumerate(df.head(5).iterrows()):
    print()
    print('--- 第 {} 行 (原始索引: {}) ---'.format(row_num + 1, idx))
    for col_idx, col_name in enumerate(df.columns):
        value = row[col_name]
        # 处理NaN值
        display_value = 'NaN' if pd.isna(value) else value
        print('  [{}] {}: {}'.format(col_idx, col_name, display_value))

print()
print('=' * 80)
print('数据查看完成')
print('=' * 80)