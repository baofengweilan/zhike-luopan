# 智课罗盘

面向个人的 AI 智能时间表助手（微信小程序）。自动处理时令作息、节假日调休、单双周等复杂时间规则，生成可执行的每日时间表。

**第五届"移动云杯"智算应用创新大赛 · AI Coding 赛参赛作品。** 作品提交截止 2026-10-15。

- 领域术语表：[CONTEXT.md](CONTEXT.md)
- 开发任务书：[project-spec.md](project-spec.md)（v4.1）
- 架构决策记录：[docs/adr/](docs/adr/)

## 结构

```
├── miniprogram/          # 原生微信小程序（TypeScript）
├── backend/              # FastAPI + SQLAlchemy 2.0 + MySQL 8
├── docker-compose.dev.yml
├── project-spec.md       # 开发任务书 v4.1
├── CONTEXT.md            # 领域术语表
└── docs/adr/             # 架构决策记录
```

## 本地开发

### 后端

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env         # 按需修改；无微信密钥时保持 WX_MOCK_LOGIN=true
alembic upgrade head               # 建表（开发默认 SQLite；配 MySQL 后自动切换）
uvicorn app.main:app --reload      # http://127.0.0.1:8000/docs
pytest                             # 后端测试
```

或用 Docker 一键起 MySQL + Redis + 后端：

```bash
docker compose -f docker-compose.dev.yml up
```

### 小程序

1. 微信开发者工具导入 `miniprogram/` 目录（测试号 `touristappid` 可直接用）
2. 详情 → 本地设置 → 勾选"不校验合法域名"
3. 编译运行：登录页 → 微信一键登录（后端 `WX_MOCK_LOGIN=true` 时返回 mock 身份）→ 首页

## 进度

- [x] 阶段一：小程序骨架 + 微信登录 + Docker Compose
- [x] 阶段二：学期 + 时令 + 作息
- [x] 阶段三：校历 + 模板 + 实例生成（含 2026 节假日种子）
- [x] 阶段 3.5：AI 最小可见闭环（规则解析应用 + 课表问答，mock 适配器）
- [x] 阶段五：实时调整 + 冲突检测 + 调整历史/回滚 + 反馈转约束
- [ ] 阶段四：教材 + 扫码 + 照片
- [ ] 阶段六：AI 完整能力 + 订阅提醒
- [ ] 阶段八：ICS 导出 + 收尾（Excel 导出砍掉）
- [ ] 二期：分享/批注/模板市场（取决于小程序主体升级）
