# 两臂研究证据归档 V1

Python 3.11 标准库项目，供循证研究协作组接纳上游两臂摘要、冻结直接比较、核对贡献并交付固定报告。无需安装依赖。从项目根目录运行，生产包使用 Python 命名空间包。

一天的工作为：管理员接收摘要 → 校验身份和统计 → 登记修订或更正/撤回 → 分析员选择明确修订 → 冻结单一治疗对 → 加工有向差值并合并 → 核账并原子发布 → 复核员读取、导出和重开核对。

## 装配与公开 API

```python
from evidence.archive.repository import Repository
from evidence.studies.revisions import StudyService, read_revision, read_current_revision
from evidence.cohorts.freeze import CohortService
from evidence.synthesis.requests import DirectAnalyzer
from evidence.results.reader import ResultReader
from evidence.results.export import ResultExporter

with Repository.open("evidence.sqlite") as repository:
    studies = StudyService(repository)
    revision = studies.put_study("trial-1", "source-v1", [
        {"treatment": "A", "mean": "1/3", "variance": "1/2"},
        {"treatment": "B", "mean": "0", "variance": "3/2"},
    ])
    cohort = CohortService(repository).freeze_cohort([revision], ("A", "B"))
    result = DirectAnalyzer(repository).analyze_direct(cohort, "A", "B")
    report = ResultReader(repository).read_result(result)
    exact_json = ResultExporter(repository).export_result(result)
```

六个主要操作是 put_study(id, source_version, arms)、withdraw_study(id, source_version)、freeze_cohort(revision_ids, treatment_pair)、analyze_direct(cohort_id, left, right)、read_result(result_id)、export_result(result_id)。另有 put_studies(entries)：每项恰含 study_id、source_version、arms；完整物化、校验并原子接纳，返回与输入顺序对应的修订 ID 元组。空批次返回空元组，无写入。身份均为非空且非全空白字符串，原样区分大小写及空格。

每臂记录恰含 treatment、mean、variance；也可传入不可变 ArmStatistics。统计接受 int、Fraction 或有限有理数字符串，拒绝 bool、float、空值、NaN 和无穷。恰有两个不同治疗臂，均值方差严格为正。mean 是同一结局尺度的均值，variance 是均值的已知方差，单位为结局单位的平方；不做样本量换算。所有计算使用 Fraction，无浮点近似。

同研究、同源版本的规范内容必须完全相同；臂重排等价。重放返回原修订且不移动当前指针；同版本不同内容（包括撤回类型）抛 ConflictError。新版本按接纳次序成为当前，不对外部版本字符串排序。撤回追加不可变修订；新有效版本可重新登记。更正与撤回不改写旧统计。

冻结保存明确修订及输入成员顺序。同一研究只能选一次；当前有效时可选历史有效修订；当前撤回后该研究任何修订均不能进入新队列。已有队列仍能分析。队列非空且全部匹配同一无序治疗对；禁止同研究的多个版本重复计权。

差值为 mean(left)-mean(right)，方差为两臂均值方差之和。原始权重 w=1/v，归一权重 q=w/sum(w)，估计 sum(w*d)/sum(w)，合并方差 1/sum(w)，逐研究贡献 q*d。反向只令差值、估计、贡献变号；权重和方差不变。examples/day.json 的差值为 1、3，方差为 2、8，应得到估计 7/5、方差 8/5 和贡献 4/5、3/5。

返回报告含 result_id、cohort_id、pair、left、right、estimate、variance、weight_sum、members。每个成员含 position、study_id、revision_id、source_version、原 arms、difference、variance、raw_weight、normalized_weight、contribution。返回值独立复制；读取和导出只恢复已存结果、检查结构与固定引用，不重新加工或合并。导出为 format_version=1 的确定性 JSON，Fraction 编成规范 [分子字符串,正分母字符串]；成员按冻结顺序、键排序，无时间戳。

## 错误、事务及历史

非法输入抛 ValueError；版本冲突抛 evidence.studies.identity.ConflictError；未知研究、修订、队列或成果抛 KeyError；当前撤回的新选择抛 ValueError。损坏历史引用、非法编码、缺失成果成员或不支持的库版本抛 evidence.archive.repository.IntegrityError，不回退当前修订。业务拒绝不新增部分状态。

研究批次、队列冻结、成果发布使用共同事务管理；嵌套调用使用保存点。成果头、证据、权重和贡献全部成功后才返回 ID。Repository.open(path, checkpoint=callback) 提供普通故障端口，callback("after_contributions") 抛出的异常原样传播并回滚，可用同一队列重试；默认不启用。应用已开启外层事务时，服务返回的 ID 仍受外层提交/回滚支配。原成果不受后续失败影响。

新库初始化建立版本 1 结构；重复 initialize() 或重开不会覆盖合法研究、更正、指针及成果。不支持的版本明确拒绝。手工破坏引用不是业务更正。关闭连接可用上下文管理器或 close()。本项目不提供并发执行承诺。

## 运行与回归

```sh
python3.11 -B -m unittest discover -s tests -v
python3.11 -B -m evidence.results.export examples/day.json
```

运行清单为 .pointwise-runtime.json，setup 为空，verify 为完整发现入口，demo 使用有限正常样例，实际登记、冻结、计算、更正、撤回、重开并核对原导出，输出实测 POINTWISE_SCENARIO 和完整报告。所有持久化回归及 demo 使用自身 TemporaryDirectory，退出清理；不读写个人资料。

24 个生产模块按研究、队列、差值、合并、成果及归档组织。tests/test_studies.py 覆盖修订和重放；test_validation.py 覆盖数值、冲突、整批及嵌套回滚；test_cohorts.py 覆盖固定选择和研究独立性；test_contrasts.py 覆盖方向；test_pooling.py 覆盖手算及贡献归属；test_publication.py 覆盖贡献后失败、重开及重试；test_history.py 覆盖更正、撤回、冻结后执行、隔离副本和重复初始化；test_export.py 独立从导出原臂核账，检查精确编码、引用损坏及读取不触发计算。任一断言失败均以非零状态结束。

V1 仅处理独立两臂研究的直接比较，不提供多臂研究、间接比较、联合网络协方差、异质性估计、治疗排名、临床建议或外部文献接入。
