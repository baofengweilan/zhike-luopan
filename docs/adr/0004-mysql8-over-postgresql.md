# 0004 - 数据库用 MySQL 8，不用 PostgreSQL

本项目参加移动云杯，赛方提供 MySQL×2 而无 PostgreSQL。为省去自维护 PG 的持久化/备份成本，主数据库改用 MySQL 8，SQLAlchemy 2.0 + Alembic 零改动兼容。迁移点：任务书的 `JSONB` → MySQL `JSON`（共 5 处）；UUID 主键用 `CHAR(36)`；`TIMESTAMP` 需显式 `DEFAULT CURRENT_TIMESTAMP`；搜索 MVP 阶段用 `LIKE` 不建 FULLTEXT。
