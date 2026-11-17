# 多臂研究与固定网络比较

本文件是新增接口的公开契约；README.md 的两臂 V1、全部原测试及原样例继续有效。network_examples.py 是手算数据与调用核验，不含网络求解器，初始 V1 尚不能执行其中的新增业务入口。

## 登记和冻结

- 在 evidence.studies.revisions.StudyService 增加 save_multiarm(id, source_version, arms)，返回整数 revision_id。arms 采用 README.md 的记录格式和精确数值规则，但允许 2～6 个不同治疗。原 put_study、put_studies 仍仅接纳两臂，原回归对三臂拒绝的要求保持有效。
- 新旧登记共用研究及源版本身份空间。同版本同规范内容复用修订，臂顺序不影响判等；同版本不同统计、臂集合或撤回类型仍抛 ConflictError，历史重放不移动当前指针。read_revision、read_current_revision 须能恢复新增修订。接纳复制输入，旧修订不得因调用方修改输入而改变。
- 在 evidence.cohorts.freeze.CohortService 增加 freeze_network(revision_ids)，返回整数 network_id。输入为明确修订 ID 的 list 或 tuple；非空、至多 80 项，治疗并集至多 20 种，允许断开的网络和不同研究治疗集合。冻结保留成员输入顺序，同研究只能贡献一个修订。沿用当前撤回阻止新选择、当前有效时可选历史有效修订、撤回修订不能作证据的规则。原 freeze_cohort 仍只接受恰好匹配其治疗对的两臂研究。
- network_id 标识持久的固定研究队列，不是分析结果。冻结不拟合，不保存请求。分析只读取这些明确修订；后续更正或撤回不能替换其证据。未知修订抛 KeyError，非法选择抛 ValueError，均不建立半队列。

研究、源版本及治疗身份均按原始非空字符串区分。不同研究、同研究不同臂的均值误差相互独立。variance 是均值的已知方差，不是个体方差，不做样本量换算。

## 联合分析

在 evidence.synthesis.requests 增加 NetworkAnalyzer(repository)，提供 analyze_network(network_id, requests)，返回持久整数 result_id。requests 是含 0～8 项的 list 或 tuple，每项是两个治疗身份组成的 list 或 tuple，表示 left 的效应减 right 的效应。保留顺序及重复；反向改变相应估计及协方差符号，自身比较为 Fraction(0)，方差和与其他可估计请求的协方差为 Fraction(0)。空请求仍核验固定证据并发布空数组。

模型为每个研究臂的 y_st = α_s + θ_t + ε_st。α_s 为自由研究截距，θ_t 为治疗效应；使用已知方差的无惩罚加权最小二乘，不估计残差尺度或异质性。请求估计是该模型的可估计线性差值；联合协方差是同一已知误差模型下估计量的协方差，不按残差缩放。全部估计和有限协方差必须为精确 Fraction。

研究加工须向网络分析交接足以保留同研究联合信息及身份的证据；可以使用固定原臂空间，也可以使用等价的相关对比表示，不规定内部类型或参照。研究、臂的顺序以及内部参照选择不得影响请求数值；更换研究内共同均值偏移也不得改变治疗差值结果。不能把多臂共同对照拆成若干独立研究。

共同出现在一个研究中的治疗属于同一连通分量。两个已知治疗同分量时请求为 estimable；跨分量时为 not_estimable，估计为 None，完整矩阵中该请求对应的整行及整列均为 None。两个可估计请求位于独立分量时协方差为 Fraction(0)。不得用任意定锚值报告跨分量效应。未知治疗抛 KeyError；非法请求形状、身份或数量抛 ValueError。任何一项未知或非法，整次不发布结果。未知 network_id 抛 KeyError。

允许全量读取固定研究及全量重算，允许标准线性代数。不要求增量、缓存、并发、排名或治疗推荐。原两臂直接分析不接受网络 ID，不改变原计算及输出规则。

## 已存成果、读取和导出

在现有 ResultReader 增加 read_network(result_id)，返回独立副本的 dict，至少包含：
- result_id、network_id：新增成果及固定队列身份；新旧成果分别通过各自读取入口解释，不要求二者整数空间互斥。
- treatments：队列中治疗身份的升序 list。
- requests：按原请求顺序保存的两元素 list 的 list。
- status：与请求等长的 estimable 或 not_estimable 字符串 list。
- estimates：按请求顺序的 Fraction 或 None 的 list。
- covariance：按请求顺序的完整方阵，元素为 Fraction 或 None；空请求时为 []。
- members：冻结顺序的 list。每项包含 position（从 0 连续计数）、study_id、revision_id、source_version、arms；arms 为按治疗身份排序的原臂记录 list，mean、variance 恢复为 Fraction。

在现有 ResultExporter 增加 export_network(result_id)，返回确定性 JSON 字符串，外层为 {"format_version":2,"result":read_network所得报告的编码}。Fraction 沿用原规范 [分子字符串,正分母字符串]；None 编为 null，列表顺序保留，键排序，无时间戳。原 export_result 的版本 1 及原负载不变。

固定队列、请求、状态、估计、矩阵及完整来源须持久保存。修改输入或返回值、更正或撤回研究、关闭重开，均不能改变旧队列、成果及导出；旧队列在更正及撤回后仍可首次分析或重新分析。读取与导出仅恢复已存结果并检查结构、编码及固定父引用，不重新构造联合证据或求解；未知成果抛 KeyError，损坏编码、缺失成员或父引用抛既有 IntegrityError，不用当前研究补全。

沿用共同事务和嵌套保存点，成果及其全部关系共同发布。新增分析也在全部成果关系写入后、提交前调用原 after_contributions 检查点；普通回调异常原样传播并回滚本次结果，保留旧结果及队列，可重试。支持原 V1 库打开及重复初始化，保全原数据；新增存储布局自行决定，但原测试中的不支持版本拒绝行为继续有效。

## 手算和交付核验

单研究 A、B、C 均值 0、1、2，方差均为 1；请求 B−A、C−A 的估计为 [1,2]，协方差为 [[2,1],[1,2]]。这是共享 A 臂误差，交叉项不能置零。独立研究 A/B 均值 0/1 和 B/C 均值 10/12、方差均为 1，C−A 估计为 3、方差为 4。只有 A/B 与 C/D 证据时，A−C 不可估计。

network_examples.py 提供上述三种有限数据、反向/重复/自身请求、空请求、重排核验及更正撤回后的磁盘重开演示。它不是完整验收或独立通用求解器；还须自行补充独立核账，覆盖混合两臂与多臂证据、参照不变性、非法输入、固定证据及发布失败重试。

交付研究接纳/固定联合证据与网络分析/成果消费的联动实现，以及简短交接说明，解释研究身份、共同对照和不可估计方向的处理。不规定内部文件划分，不要求改动仍正确的 V1 标量加工函数。

保留并扩展 .pointwise-runtime.json：沿用已有字段格式，verify 实际运行全部原回归和新增网络核验，demo 展示共同对照矩阵以及更正后重开旧成果；失败须以非零状态结束。原 demo 保持可运行。新增调用样例可分别以 python3.11 -B network_examples.py --verify 和 --demo 执行。
