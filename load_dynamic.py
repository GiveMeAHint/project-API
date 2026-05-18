import sqlite3
import pandas as pd
import sys

DB_PATH = "project.db" 
EXCEL_PATH = "Statistika_dlya_analiza.xlsx"

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA foreign_keys = ON")
cursor = conn.cursor()

cursor.execute("SELECT id, name FROM programs")
program_map = {row[1].strip().lower(): row[0] for row in cursor.fetchall()}

df = pd.read_excel(EXCEL_PATH, sheet_name="Лист1", header=[0, 1])

new_cols = []
for col in df.columns:
    if isinstance(col, tuple):
        # Отфильтровываем пустые значения и NaN, преобразуем всё в str
        parts = [str(c) for c in col if str(c).strip().lower() not in ['nan', '']]
        new_cols.append("_".join(parts).strip())
    else:
        new_cols.append(str(col).strip())
df.columns = new_cols

prog_col = next((c for c in df.columns if "направления" in c.lower()), None)
if not prog_col:
    print(" Не найден столбец с направлениями подготовки")
    sys.exit(1)

df["Направления подготовки"] = df[prog_col].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()

years = [2019, 2020, 2021, 2022, 2023]
quotas_data = []
apps_data = []

for _, row in df.iterrows():
    prog_name = row.get("Направления подготовки")
    if pd.isna(prog_name) or prog_name.lower() == "nan": 
        continue
    
    prog_key = prog_name.lower()
    if prog_key not in program_map:
        continue 
        
    prog_id = program_map[prog_key]
    
    for year in years:
        budget_col = next((c for c in df.columns if str(year) in c and "бюджетных" in c.lower()), None)
        apps_col = next((c for c in df.columns if str(year) in c and "заявлений" in c.lower()), None)
        enroll_col = next((c for c in df.columns if str(year) in c and ("зачисленных" in c.lower() or "зачисленых" in c.lower())), None)
        
        if budget_col and apps_col:
            budget = int(float(row[budget_col])) if pd.notna(row[budget_col]) else 0
            apps = int(float(row[apps_col])) if pd.notna(row[apps_col]) else 0
            enroll = int(float(row[enroll_col])) if pd.notna(row[enroll_col]) else 0
            
            if budget > 0 or apps > 0:
                quotas_data.append((year, prog_id, budget))
                apps_data.append((year, prog_id, apps, enroll))

cursor.executemany("""
    INSERT OR IGNORE INTO quotas (year, program_id, spots) 
    VALUES (?, ?, ?)
""", quotas_data)
print(f" Загружено записей КЦП: {len(quotas_data)}")

cursor.executemany("""
    INSERT OR IGNORE INTO applications (year, program_id, app_count, enrolled_count) 
    VALUES (?, ?, ?, ?)
""", apps_data)
print(f" Загружено записей заявлений: {len(apps_data)}")

conn.commit()
conn.close()
print(" Динамические данные успешно загружены")