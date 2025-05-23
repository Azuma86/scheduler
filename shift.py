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
weekday_reqs = {}
for wd in range(7):
    req = st.sidebar.number_input(
    f"{weekday_map[wd]}曜日 必要人数", 0, 20, 2, key=f"wd_req_{wd}")
    weekday_reqs[wd] = req

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
fixed_defs = []
if shift_mode == "固定シフト":
    st.sidebar.subheader("▶ 固定シフト定義")
    n_fix = st.sidebar.number_input("シフト数", 1, 10, 2)
    for i in range(n_fix):
        name = st.sidebar.text_input(f"シフト{i+1} 名称", f"シフト{i+1}", key=f"fix_name{i}")
        start = st.sidebar.time_input(f"{name} 開始", datetime.time(9, 0), key=f"fix_start{i}")
        end = st.sidebar.time_input(f"{name} 終了", datetime.time(13, 0), key=f"fix_end{i}")
        req = {}
        for role in roles:
            req[role] = st.sidebar.number_input(
                f"{role} 必要人数", 0, 10, 1, key=f"fix_req{i}_{role}"
            )
        fixed_defs.append({"name": name, "start": start, "end": end, "req": req})
else:
    st.sidebar.subheader("▶ フリーシフト設定")
    biz_start = st.sidebar.time_input("営業時間 開始", datetime.time(17, 0))
    biz_end = st.sidebar.time_input("営業時間 終了", datetime.time(23, 0))
    free_defs = []
    for h in range(biz_start.hour, biz_end.hour):
        slot = f"{h:02d}:00–{h+1:02d}:00"
        req = {}
        for role in roles:
            req[role] = st.sidebar.number_input(
                f"{slot} の{role}人数", 0, 10, 1, key=f"free_req{h}_{role}"
            )
        free_defs.append({"slot": slot, "start": datetime.time(h, 0), "end": datetime.time(h+1, 0), "req": req})

# CSVアップロード
uploaded = st.file_uploader("スタッフ希望CSVをアップロード", type="csv")
if not uploaded:
    st.info("まずは希望CSVをアップロードしてください。")
    st.stop()

# データ準備
df = pd.read_csv(uploaded)
for col in ["開始時刻", "終了時刻"]:
    df[col] = df[col].apply(lambda s: datetime.datetime.strptime(s.strip(), "%H:%M").time() if isinstance(s, str) else None)

staffs = df['名前'].unique().tolist()
core_members = st.sidebar.multiselect("主要メンバーを選択 (各タスクに最低1名)", staffs)

st.subheader("スタッフ希望一覧")
st.dataframe(df)

st.subheader("スタッフごとの対応可能役割")
staff_roles = {}
for p in staffs:
    staff_roles[p] = st.multiselect(f"{p} の役割", roles, default=roles)


# 最適化モデル実行
if st.button("⚙️ 自動割り当て実行"):
    model = cp_model.CpModel()

    # タスク定義
    tasks = []  # (id, start_min, end_min, req_dict)
    def to_min(t): return t.hour*60 + t.minute
    if shift_mode == "固定シフト":
        for idx, sd in enumerate(fixed_defs):
            tasks.append((sd['name'], to_min(sd['start']), to_min(sd['end']), sd['req']))
    else:
        for fd in free_defs:
            tasks.append((fd['slot'], to_min(fd['start']), to_min(fd['end']), fd['req']))

    # 変数定義 x[(task, person, role)]
    x = {}
    for t_id, t_s, t_e, req in tasks:
        for role, rnum in req.items():
            for p in staffs:
                # 時刻・役割フィルタ
                if role in staff_roles[p] and not df[(df['名前']==p) & (df['開始時刻']<= datetime.time(t_s//60, t_s%60)) & (df['終了時刻']>= datetime.time(t_e//60, t_e%60))].empty:
                    x[(t_id, p, role)] = model.NewBoolVar(f"x_{t_id}_{p}_{role}")

    # 条件1: 必要人数の満足
    for t_id, _, _, req in tasks:
        for role, rnum in req.items():
            vars_ = [x[(t_id, p, role)] for p in staffs if (t_id, p, role) in x]
            model.Add(sum(vars_) == rnum)

    # 条件2: タスク内排他
    for t_id, _, _, _ in tasks:
        for p in staffs:
            vars_ = [x[(t_id, p, role)] for role in roles if (t_id, p, role) in x]
            if vars_:
                model.Add(sum(vars_) <= 1)

    # 条件3: 休憩時間ルール
    if "休憩時間ルール" in criteria:
        for i, (t1, s1, e1, _) in enumerate(tasks):
            for j, (t2, s2, e2, _) in enumerate(tasks):
                if i >= j: continue
                # 連続勤務時間が閾値超? and 休憩挿入が必要?
                dur1 = (e1 - s1)
                if dur1 >= threshold_hours*60:
                    # 次の開始が休憩時間内なら禁止
                    if s2 < e1 + break_hours*60 and s2 >= s1:
                        for p in staffs:
                            for r1 in roles:
                                for r2 in roles:
                                    if (t1, p, r1) in x and (t2, p, r2) in x:
                                        model.Add(x[(t1, p, r1)] + x[(t2, p, r2)] <= 1)

    # 条件4: 1日最大勤務時間
    if "1日あたり最大勤務時間" in criteria:
        for p in staffs:
            terms = []
            for t_id, t_s, t_e, _ in tasks:
                dur = (t_e - t_s)
                for role in roles:
                    if (t_id, p, role) in x:
                        terms.append(x[(t_id, p, role)] * dur)
            if terms:
                model.Add(sum(terms) <= max_daily_hours*60)

    # 条件5: コアメンバー保証
    if core_members:
        for t_id, _, _, _ in tasks:
            core_vars = []
            for p in core_members:
                for role in roles:
                    if (t_id, p, role) in x:
                        core_vars.append(x[(t_id, p, role)])
            if core_vars:
                model.Add(sum(core_vars) >= 1)

    # 目的: 勤務回数偏り
    if "勤務回数の偏りを抑える" in criteria:
        assign_cnt = {p: model.NewIntVar(0, len(tasks), f"cnt_{p}") for p in staffs}
        for p in staffs:
            terms = []
            for t_id, _, _, _ in tasks:
                for role in roles:
                    if (t_id, p, role) in x:
                        terms.append(x[(t_id, p, role)])
            if terms:
                model.Add(assign_cnt[p] == sum(terms))
        max_c = model.NewIntVar(0, len(tasks), "max_c")
        min_c = model.NewIntVar(0, len(tasks), "min_c")
        model.AddMaxEquality(max_c, list(assign_cnt.values()))
        model.AddMinEquality(min_c, list(assign_cnt.values()))
        model.Minimize(max_c - min_c)

    # ソルバー実行
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    res = solver.Solve(model)

    # 割当結果抽出
    assigned = []
    if res == cp_model.OPTIMAL or res == cp_model.FEASIBLE:
        for (t_id, p, role), var in x.items():
            if solver.Value(var) == 1:
                start = datetime.time(*divmod(next(s for tid,s,_,_ in tasks if tid==t_id)[1],60))
                end =   datetime.time(*divmod(next((s,_,e,_) for tid,s,e,_ in tasks if tid==t_id)[2],60))
                assigned.append({"名前":p, "タスク":t_id, "役割":role,
                                  "時間":f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"})
    else:
        st.error("解が見つかりませんでした。制約を緩めてください。")

    # DataFrame生成
    df_res = pd.DataFrame(assigned)
    st.subheader("🎉 割り当て結果")
    st.dataframe(df_res)

    # 不足シフトの報告
    missing = []
    for t_id, _, _, req in tasks:
        for role, rnum in req.items():
            assigned_n = len([1 for a in assigned if a['タスク']==t_id and a['役割']==role])
            if assigned_n < rnum:
                missing.append({"タスク":t_id, "役割":role,
                                "不足数":rnum - assigned_n})
    if missing:
        st.subheader("⚠️ 不足シフト")
        st.dataframe(pd.DataFrame(missing))

    # CSVダウンロード
    st.download_button(
        "CSVダウンロード",
        df_res.to_csv(index=False).encode("utf-8"),
        "optimized_schedule.csv",
        "text/csv"
    )
