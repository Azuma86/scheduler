@dataclass
class Task:
    id: str
    start: int     # 分単位
    end: int       # 分単位
    req: dict      # {role: needed_count}
    date: datetime.date

def to_minutes(t: datetime.time) -> int:
    return t.hour * 60 + t.minute

def generate_tasks(
    start_date, end_date, shift_mode, fixed_defs, free_defs
):
    tasks = []
    cur = start_date
    while cur <= end_date:
        if shift_mode == "固定シフト":
            for sd in fixed_defs:
                tasks.append(Task(
                    id=f"{cur}_{sd['name']}",
                    start=to_minutes(sd['start']),
                    end=to_minutes(sd['end']),
                    req=sd['req'],
                    date=cur
                ))
        else:
            for fd in free_defs:
                tasks.append(Task(
                    id=f"{cur}_{fd['slot']}",
                    start=to_minutes(fd['start']),
                    end=to_minutes(fd['end']),
                    req=fd['req'],
                    date=cur
                ))
        cur += datetime.timedelta(days=1)
    return tasks

def optimize_schedule(
    tasks, staffs, staff_roles, criteria,
    max_daily_hours, threshold_hours, break_hours, core_members
):
    model = cp_model.CpModel()
    x = {}
    # 変数定義
    for t in tasks:
        for role, cnt in t.req.items():
            for p in staffs:
                if role in staff_roles[p]:
                    x[(t.id,p,role)] = model.NewBoolVar(f"x[{t.id},{p},{role}]")
    # 制約① 必要人数
    for t in tasks:
        for role, cnt in t.req.items():
            vars_ = [x[(t.id,p,role)] for p in staffs if (t.id,p,role) in x]
            model.Add(sum(vars_) >= cnt)
    # 制約② 同一タスク内で1人1役
    for t in tasks:
        for p in staffs:
            vars_ = [x[(t.id,p,role)] for role in staff_roles[p] if (t.id,p,role) in x]
            if vars_:
                model.Add(sum(vars_) <= 1)
    # 制約③ 休憩ルール
    if "休憩時間ルール" in criteria:
        tasks_sorted = sorted(tasks, key=lambda t:(t.date, t.start))
        for i in range(len(tasks_sorted)-1):
            t1, t2 = tasks_sorted[i], tasks_sorted[i+1]
            if t1.date == t2.date and (t1.end - t1.start) >= threshold_hours*60:
                if t2.start < t1.end + break_hours*60:
                    for p in staffs:
                        for r1 in staff_roles[p]:
                            for r2 in staff_roles[p]:
                                k1, k2 = (t1.id,p,r1), (t2.id,p,r2)
                                if k1 in x and k2 in x:
                                    model.Add(x[k1] + x[k2] <= 1)
    # 制約④ 1日最大勤務時間
    if "1日あたり最大勤務時間" in criteria:
        limit = int(max_daily_hours*60)
        for date in {t.date for t in tasks}:
            for p in staffs:
                terms = []
                for t in tasks:
                    if t.date==date:
                        dur = t.end - t.start
                        for role in staff_roles[p]:
                            key = (t.id,p,role)
                            if key in x:
                                terms.append(x[key]*dur)
                if terms:
                    model.Add(sum(terms) <= limit)
    # 制約⑤ コアメンバー保証
    if core_members:
        for t in tasks:
            core_terms = [x[(t.id,p,role)]
                          for p in core_members
                          for role in staff_roles[p]
                          if (t.id,p,role) in x]
            if core_terms:
                model.Add(sum(core_terms) >= 1)
    # 目的：勤務回数の偏りを抑える
    if "勤務回数の偏りを抑える" in criteria:
        counts = {p: model.NewIntVar(0,len(tasks),f"cnt_{p}") for p in staffs}
        for p in staffs:
            cnt_terms = [x[(t.id,p,role)]
                         for t in tasks for role in staff_roles[p]
                         if (t.id,p,role) in x]
            model.Add(counts[p]==sum(cnt_terms))
        max_c = model.NewIntVar(0,len(tasks),"max_c")
        min_c = model.NewIntVar(0,len(tasks),"min_c")
        model.AddMaxEquality(max_c,list(counts.values()))
        model.AddMinEquality(min_c,list(counts.values()))
        model.Minimize(max_c-min_c)
    # ソルブ
    solver=cp_model.CpSolver()
    solver.parameters.max_time_in_seconds=30
    res=solver.Solve(model)
    assigned, missing = [], []
    if res in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        for (tid,p,role),var in x.items():
            if solver.Value(var):
                t = next(t for t in tasks if t.id==tid)
                assigned.append({
                    "日付":t.date, "タスク":tid,
                    "名前":p, "役割":role,
                    "時間":f\"{t.start//60:02d}:{t.start%60:02d}–{t.end//60:02d}:{t.end%60:02d}\"
                })
        for t in tasks:
            for role,cnt in t.req.items():
                got = sum(1 for a in assigned if a["タスク"]==t.id and a["役割"]==role)
                if got<cnt:
                    missing.append({"日付":t.date,"タスク":t.id,"役割":role,"不足数":cnt-got})
    else:
        st.error("解が見つかりませんでした。制約を緩めてください。")
    return assigned, missing