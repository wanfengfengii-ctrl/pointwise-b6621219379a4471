# 多臂网络链路交接说明

本说明配套 NETWORK.md 契约与 network_examples.py 手算样例，面向接收该工程的核账与复核同事。两臂 V1 的行为、编码和回归以 README.md 为准，未做改动。

## 研究身份与修订

- 新旧登记共用同一研究/源版本身份空间：`put_study`/`put_studies` 仍只接纳两臂，`save_multiarm` 接纳 2～6 个不同治疗臂。两臂内容用任一入口登记都得到同一修订。
- 同一 (study_id, source_version) 的规范内容（臂集合与各臂精确统计，臂序无关）复用原修订且不移动当前指针；同版本不同统计、不同臂集合或撤回类型抛 ConflictError。接纳时复制输入，之后调用方改输入不影响已存修订。
- 更正追加新修订并成为当前；撤回追加空臂撤回修订；旧修订永不被改写。`freeze_network` 只接受明确修订 ID：当前撤回的研究不能再进新队列，当前有效时可选历史有效修订，撤回修订本身不能作证据。已冻结队列不受后续更正/撤回影响，仍可首次或再次分析。
- 队列上限 80 研究、20 治疗，同研究只贡献一个修订；允许断开的网络和不同研究治疗集合。冻结只保存成员顺序，不拟合、不保存请求。

## 共同对照与联合证据

- 多臂研究不拆成若干独立两臂。研究加工把同一修订的全部臂连同 (position, study_id, revision_id) 一起交接给网络分析（evidence/synthesis/network.py 的 NetworkStudyEvidence），同研究臂间共享研究截距，跨研究及同研究不同臂的误差独立。
- 模型 y_st = α_s + θ_t + ε_st，α_s 自由、θ_t 为治疗效应；用已知方差的无惩罚加权最小二乘，不估残差尺度与异质性，协方差不按残差缩放。实现按研究精确剖离 α_s 得到治疗上的约化信息矩阵（分量 Laplacian），约束分量内参照 θ=0 后精确求逆；全部运算用 Fraction，无浮点。
- 共同对照的误差因此进入交叉项：单研究 A/B/C 方差均为 1 时，B−A 与 C−A 的协方差为 1（共享 A 臂），不能置零。参照选择、研究顺序、臂顺序、同研究共同均值平移都不改变任何可估计差值——精确算术下这些是恒等不变量。
- 发布前独立核账：用冻结臂重建各分量正规方程，验证 A·θ̂=b 与 A·V=I（代入验证而非重解），并核对请求估计/协方差与解的线性组合一致；全部成果关系写入后、提交前触发原 after_contributions 检查点，回调异常原样传播并回滚本次结果，旧成果与队列保留，可重试。

## 不可估计方向

- 同一研究中出现的治疗属于同一连通分量。请求两端为已知治疗且同分量时为 estimable，估计为 θ 差值；跨分量为 not_estimable，估计为 None，协方差矩阵中该请求的整行整列均为 None，不用任何定锚值冒充跨分量效应。
- 两个可估计请求若分属独立分量，协方差精确为 0；自身比较（如 A−A）估计为 0，与其他可估计请求的协方差为 0。请求保留顺序与重复，反向只改变相应估计与协方差符号。
- 未知治疗抛 KeyError，请求形状/身份/数量（0～8 项）非法抛 ValueError；任一项非法则整次不发布。未知 network_id 抛 KeyError。

## 存储、读取与核验

- 库版本仍为 1；新库一次建齐全部表，打开纯 V1 库时原地增补 networks/network_members/network_results/network_result_members 四张表，原数据不动；版本不符或结构不符仍抛 IntegrityError。新旧成果整数空间各自独立，分别经 read_result/read_network 解释。
- 成果持久保存固定队列引用、请求、状态、估计、完整协方差及完整来源（成员含 position、study_id、revision_id、source_version 与排序原臂）。read_network/export_network 只恢复已存数据并做结构、编码与父引用检查，不重算；导出为 format_version=2 的确定性 JSON，Fraction 编为 [分子,正分母]，None 编为 null。
- 核验入口：`python3.11 -B -m unittest discover -s tests -v`（全部原回归加 tests/test_network.py，内含独立全设计矩阵核账、参照/顺序/平移不变性、非法输入、固定证据、发布失败重试与磁盘重开）；`python3.11 -B network_examples.py --verify` 与 `--demo`（共同对照矩阵、更正后重开旧成果）；原 demo `python3.11 -B -m evidence.results.export examples/day.json` 保持可运行。
