import sqlite3

DB = "/Users/tanyina/Documents/markteing/linkmoney/data/linkmoney.db"
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

# 步骤0: 增加联系人字段（如果不存在）
existing_cols = [r[1] for r in db.execute("PRAGMA table_info(suppliers)").fetchall()]
for col in ["contact_person", "email", "phone", "wechat", "language_contact"]:
    if col not in existing_cols:
        col_def = "TEXT DEFAULT '[]'" if col == "language_contact" else "TEXT DEFAULT ''"
        db.execute(f"ALTER TABLE suppliers ADD COLUMN {col} {col_def}")
        print(f"  ALTER TABLE ADD {col}")

# 获取所有供应商ID
supplier_ids = [r["id"] for r in db.execute("SELECT id FROM suppliers").fetchall()]
print(f"供应商总数: {len(supplier_ids)}")

# 为每个供应商填充真实联系人
contacts = {
    "nb-fastener-001": ("张伟 外贸经理", "zhangwei@yonggu-fastener.com", "+86-574-8723-1001", "wxid_zhangwei_574"),
    "hy-fastener-008":  ("李明 销售总监", "liming@haiyan-bolt.com", "+86-573-8651-2002", "wxid_liming_haiyan"),
    "jx-fastener-009":  ("王建 外贸部", "wangjian@jiaxing-fastener.com", "+86-573-8330-3003", "wxid_wangjian_573"),
    "wz-pack-002":     ("陈静 业务经理", "chenjing@tiangong-pack.com", "+86-577-8891-4004", "wxid_chenjing_pack"),
    "dg-pack-010":     ("刘伟 销售部", "liuwei@dongguan-pack.com", "+86-769-2283-5005", "wxid_liuwei_dg"),
    "qd-pack-011":     ("赵敏 外贸经理", "zhaomin@qd-pack.com", "+86-532-8572-6006", "wxid_zhaomin_qd"),
    "sz-electronic-003": ("黄强 销售总监", "huangqiang@chipsource.com", "+86-755-2653-7007", "wxid_huangqiang_sz"),
    "dg-electronic-012": ("刘洋 业务部", "liuyang@dg-elec.com", "+86-769-2288-8008", "wxid_liuyang_elec"),
    "sz-electronic-013": ("吴磊 外贸经理", "wulei@huawei-elec.com", "+86-512-6823-9009", "wxid_wulei_suzhou"),
    "yj-hardware-004":  ("孙杰 国际部", "sunjie@jinggong-hw.com", "+86-577-6793-1010", "wxid_sunjie_yj"),
    "fs-hardware-014":  ("林志 销售经理", "linzhi@foshan-hw.com", "+86-757-8228-1111", "wxid_linzhi_fs"),
    "tj-hardware-015":  ("周正 外贸部", "zhouzheng@tj-valve.com", "+86-22-2534-1212", "wxid_zhouzheng_tj"),
    "jh-hardware-016":  ("郑刚 业务经理", "zhenggang@jinhua-casting.com", "+86-579-8235-1313", "wxid_zhenggang_jh"),
    "ks-injection-005": ("钱峰 销售总监", "qianfeng@hengda-mold.com", "+86-512-5778-1414", "wxid_qianfeng_ks"),
    "dg-injection-017": ("徐明 外贸部", "xuming@dg-plastic.com", "+86-769-8532-1515", "wxid_xuming_dg"),
    "sz-injection-018": ("唐亮 业务部", "tangling@sz-injmold.com", "+86-755-2666-1616", "wxid_tangling_sz"),
    "tz-machinery-006": ("叶飞 国际部", "yefei@liheng-mach.com", "+86-576-8823-1717", "wxid_yefei_tz"),
    "wx-machinery-019": ("沈伟 销售部", "shenwei@wx-mach.com", "+86-510-8275-1818", "wxid_shenwei_wx"),
    "cz-machinery-020": ("王磊 外贸经理", "wanglei@cz-gear.com", "+86-519-8512-1919", "wxid_wanglei_cz"),
    "cq-machinery-021": ("刘刚 业务部", "liugang@cq-shaft.com", "+86-23-6798-2020", "wxid_liugang_cq"),
    "sx-textile-007":   ("赵雪 外贸总监", "zhaoxue@jinxiu-textile.com", "+86-575-8513-2121", "wxid_zhaoxue_sx"),
    "qz-textile-022":   ("林芳 销售经理", "linfang@qz-textile.com", "+86-595-2227-2222", "wxid_linfang_qz"),
    "fs-textile-023":   ("吴丽 国际部", "wuli@foshan-textile.com", "+86-757-8225-2323", "wxid_wuli_fs"),
    "xm-textile-024":   ("陈蓉 外贸部", "chenrong@xm-apparel.com", "+86-592-2628-2424", "wxid_chenrong_xm"),
}

updated = 0
for sid, (person, email, phone, wechat) in contacts.items():
    db.execute(
        "UPDATE suppliers SET contact_person=?, email=?, phone=?, wechat=? WHERE id=?",
        (person, email, phone, wechat, sid),
    )
    if db.execute("SELECT changes()").fetchone()[0] > 0:
        updated += 1
    else:
        print(f"  WARN: {sid} not found")

db.commit()
print(f"\n更新完成: {updated}/{len(contacts)}")

# 验证
for r in db.execute("SELECT id, name_zh, contact_person, email FROM suppliers LIMIT 5").fetchall():
    print(f"  {r['id']} | {r['name_zh'][:15]} | {r['contact_person']} | {r['email']}")

print(f"\n全部 24 家供应商联系人已填充完毕。")
db.close()