import streamlit as st
import pandas as pd
import datetime
from ortools.sat.python import cp_model



# アプリタイトル
st.title("Opt Shift🗓️")

# ===== 管理者設定 =====
st.sidebar.header("🛠 管理者設定")
#シフト作成期間
start_date = st.sidebar.date_input("シフト開始日", datetime.date.today())
end_date = st.sidebar.date_input("シフト終了日", datetime.date.today() + datetime.timedelta(days=13))
st.sidebar.markdown(f"期間: {start_date} 〜 {end_date} ({(end_date-start_date).days+1}日間)")

# 役割定義
roles_txt = st.sidebar.text_input("役割（カンマ区切り）", "キッチン, ホール")
roles = [r.strip() for r in roles_txt.split(',') if r.strip()]

# 固定／フリー切替
shift_mode = st.sidebar.radio("シフトタイプ", ["固定シフト", "フリーシフト"])

# 主要メンバー
core_members = []  # CSV読み込み後に再設定

# 割り当て基準
criteria = st.sidebar.multiselect(
    "割り当て基準を選択",
    [
        "勤務回数の偏りを抑える",
        "希望削られ率の偏りを抑える",
        "1日あたり最大勤務時間",
        "休憩時間ルール"
    ]
)


if "1日あたり最大勤務時間" in criteria:
    # 1日最大勤務時間（時間）
    max_daily_hours = st.sidebar.number_input(
        "1日あたりの最大勤務時間 (h)", min_value=1.0, max_value=24.0, value=6.0, step=0.5
    )
if "休憩時間ルール" in criteria:
    # 休憩時間ルール設定
    threshold_hours = st.sidebar.number_input(
        "休憩を必要とする勤務時間 (h)", min_value=0.0, max_value=24.0, value=4.0, step=0.5
    )
    break_hours = st.sidebar.number_input(
        "休憩時間 (h)", min_value=0.0, max_value=8.0, value=1.0, step=0.5
    )

st.sidebar.subheader("▶ 曜日ごとの必要人数設定")
weekday_map = {0: '月',1:'火',2:'水',3:'木',4:'金',5:'土',6:'日'}
weekday_reqs = {'月':[],'火':[],'水':[],'木':[],'金':[],'土':[],'日':[]}
n_fix = {'月':[],'火':[],'水':[],'木':[],'金':[],'土':[],'日':[]}
if shift_mode == "固定シフト":
    st.sidebar.subheader("▶ 固定シフト定義")
    for wd in range(7):
        exp = st.sidebar.expander(f"▶ {weekday_map[wd]}曜日")
        n_fix[weekday_map[wd]] = exp.number_input("シフト数", 1, 10, 2,key=f"nfix_{wd}")
        for i in range(n_fix[weekday_map[wd]]):
            name = exp.text_input(f"シフト{i+1} 名称", f"シフト{i+1}", key=f"{wd}fix_name{i}")
            start = exp.time_input(f"{name} 開始", datetime.time(9, 0), key=f"{wd}fix_start{i}")
            end = exp.time_input(f"{name} 終了", datetime.time(13, 0), key=f"{wd}fix_end{i}")
            req = {}
            for role in roles:
                req[role] = exp.number_input(
                    f"{role} 必要人数", 0, 10, 1, key=f"{wd}fix_req{i}_{role}"
                )
            weekday_reqs[weekday_map[i]].append({"name": name, "start": start, "end": end, "req": req})
else:
    st.sidebar.subheader("▶ フリーシフト設定")

    for wd in range(7):
        exp = st.sidebar.expander(f"▶ {weekday_map[wd]}曜日")
        biz_start = exp.time_input("営業時間 開始", datetime.time(17, 0),key=f"nfix_{wd}")
        biz_end = exp.time_input("営業時間 終了", datetime.time(23, 0),key=f"nfix{wd}")
        for h in range(biz_start.hour, biz_end.hour):
            slot = f"{h:02d}:00–{h+1:02d}:00"
            req = {}
            for role in roles:
                req[role] = exp.number_input(
                    f"{slot} の{role}人数", 0, 10, 1, key=f"{wd}free_req{h}_{role}"
                )
            weekday_reqs[weekday_map[wd]].append({"slot": slot, "start": datetime.time(h, 0), "end": datetime.time(h+1, 0), "req": req})


st.sidebar.subheader("▶ 特別日設定")
special_dates = st.sidebar.multiselect(
"特別日を選択 (期間内の日付)",
[start_date + datetime.timedelta(days=i) for i in range((end_date-start_date).days+1)],
format_func=lambda d: d.strftime('%Y-%m-%d')
)
special_reqs = {}
for sd in special_dates:
    special_reqs[sd] = st.sidebar.number_input(
    f"{sd} 必要人数", 0, 20, weekday_reqs[sd.weekday()], key=f"sp_req_{sd}")
    
# 固定シフト設定

# CSVアップロード
uploaded = st.file_uploader("スタッフ希望CSVをアップロード", type="csv")
if not uploaded:
    st.info("まずは希望CSVをアップロードしてください。")
    st.stop()

# データ準備

df = pd.read_csv(uploaded)
df['日付'] = pd.to_datetime(df['日付'])
df['weekday'] = df['日付'].dt.weekday
ndf = df.copy()
ndf['開始時刻'] = pd.to_datetime(ndf['開始時刻'],format='%H:%M').dt.time
ndf['終了時刻'] = pd.to_datetime(ndf['終了時刻'],format='%H:%M').dt.time
staffs = ndf['名前'].unique().tolist()
core_members = st.sidebar.multiselect("主要メンバーを選択 (各タスクに最低1名)", staffs)

st.subheader("スタッフ希望一覧")
st.dataframe(df)

st.subheader("スタッフごとの対応可能役割")
staff_roles = {}
for p in staffs:
    staff_roles[p] = st.multiselect(f"{p} の役割", roles, default=roles)

tasks = generate_tasks(start_date,end_date,shift_mode,fixed_defs,free_defs)
if st.button("⚙️ 自動割り当て実行"):
    assigned, missing = optimize_schedule(
        tasks, staffs, staff_roles, criteria,
        max_daily_hours, threshold_hours, break_hours, core_members
    )
    st.subheader("🎉 割り当て結果")
    st.dataframe(pd.DataFrame(assigned))
    if missing:
        st.subheader("⚠️ 不足シフト")
        st.dataframe(pd.DataFrame(missing))

    # DataFrame生成
    df_res = pd.DataFrame(assigned)
    st.subheader("🎉 割り当て結果")
    st.dataframe(df_res)

    
    # CSVダウンロード
    st.download_button(
        "CSVダウンロード",
        df_res.to_csv(index=False).encode("utf-8"),
        "optimized_schedule.csv",
        "text/csv"
    )
