# 134城公积金贷款最高额度核验更新

## 目标
逐城核验现行公积金贷款最高额度（单人/家庭/上浮政策），刷新数据库 loan 字段，升级 v1.4.0。

## 阶段
1. **采集（8个并行explore子代理）**：135城按地区分8批，每批17城左右
   - 每城搜索：该市现行公积金贷款最高额度（首套/二套、单人/双缴存）
   - 重点核验2025-2026年调整（多子女/人才/绿色建筑/现房等上浮政策）
   - 输出 /mnt/agents/output/research/maxloan_batch_N.json
   - 铁律：真实可点击来源链接，官网优先，找不到记null+说明，禁止编造
2. **合并入库**：更新 loan.max_single / loan.max_family / note / sources，版本→1.4.0
3. **同步4副本**：主JSON / project/data/ / frontend-example/db.json / app/db.json
4. **提交仓库 + 保存网站版本 + 生成对比报告**
