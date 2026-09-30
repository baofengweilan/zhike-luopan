# 智课罗盘 — 企业级项目开发任务书（微信小程序版）

**版本：** v4.1  
**目标读者：** ZCode Agent  
**项目类型：** 微信小程序 + 自建后端（个人工具类）  
**参赛：** 第五届"移动云杯"智算应用创新大赛 · **AI Coding 赛**（作品提交截止 **2026-10-15**，初赛/复赛 10.16–11.8，总决赛 12 月）  
**评审五维度：** AI 编码能力运用、创新性、技术实现、应用价值、展示与文档（五项并列，各阶段与维度的对应见第 6 章前言）  
**文档性质：** 可执行的完整开发任务书，ZCode 可按文档直接开发

### v4.1 变更摘要（经三轮拷问定稿，决策详见 docs/adr/）

1. **前端改原生小程序**（WXML/WXSS + TypeScript），弃用 uni-app（ADR-0001）
2. **AI 服务改移动云 MoMA 平台**，弃用智谱 API 直连（ADR-0002）
3. **MVP 裁剪** = 验收项 A01–A18 + A23；阶段 7 推迟二期（ADR-0003）
4. **数据库改 MySQL 8**，跟随比赛资源；`JSONB`→`JSON`，UUID 用 `CHAR(36)`（ADR-0004）
5. **节假日静态种子数据**，运行时零外部节假日 API（ADR-0005）
6. **删除 OR-Tools CP-SAT**（无算法真正使用）
7. **AI 能力前置**：阶段 3 后插入"AI 解析规则 + AI 问答（mock）"，匹配 web coding 赛道评审重点
8. **订阅消息两条模板**（课前/调课、假期/时令），一次性授权额度耗尽降级站内提醒
9. **课表视图定为"今日列表 + 横向滚动周卡片"**，正式开发前先 `/prototype` 验证
10. **第 1 周锚点** = 学期 start_date 所在完整自然周（周一起算）


## 第 1 章 项目概述

### 1.1 项目定位

智课罗盘是一个**面向个人的 AI 智能时间表助手**，以**微信小程序**为载体。用户可以导入课表或手动创建个人日程，系统自动处理春/夏/秋/冬时令作息、国家法定节假日、调休补班、单双周、连堂等复杂时间规则，生成真正可执行的每日时间表。每节课可绑定教材，支持微信扫码 ISBN 一键录入，展示教材封面。支持课前提醒、时令切换提醒、节假日调休提醒。支持课表分享给同学/家人，支持协作批注，支持模板市场共享。

**核心定位：个人工具，不是学校教务系统。** 不需要多角色权限、审批流、教务发布、学校统一管理等功能。每个用户独立管理自己的时间表。

### 1.2 目标用户

学生、教师、家长、上班族、自由职业者、自由学习者。任何需要管理个人时间安排的人。

### 1.3 核心价值

1. **自动适配时令与节次**：消除“第 3 节到底几点”的困惑
2. **动态同步国家节假日与调休**：不再手动维护每年变化
3. **AI 生成 + 个人实时调整 + 主动提醒**：可点击调整、自然语言调课、反馈纠错
4. **教材视觉识别 + 微信扫码一键录入**：扫 ISBN 自动获取书名、封面，一眼确认带哪本书
5. **教室/楼栋外观展示**：上传照片，提前认教室、认楼
6. **版本留痕与回滚**：每次调整可追溯、可对比、可回滚
7. **协作批注 + 模板市场**：与同学/家人分享课表、批注讨论，共享时令作息模板
8. **微信订阅消息提醒**：课前、调课、假期、时令切换，微信服务通知触达

### 1.4 微信小程序关键变化

| 原 Web 方案 | 微信小程序方案 |
|---|---|
| Vue3 + FullCalendar | 原生小程序 + TypeScript + 自研课表组件（今日列表 + 横向滚动周卡片） |
| 浏览器通知 | 微信订阅消息 |
| ZXing-js 扫码 | `wx.scanCode` 原生扫码 |
| Axios | `wx.request` 封装 |
| 浏览器文件下载 | 后端生成文件 + `wx.downloadFile` + `wx.openDocument` |
| 分享链接 | `onShareAppMessage` + 分享码 |
| 内容审核 | 微信内容安全 API：`security.msgSecCheck`、`security.mediaCheckAsync` |
| 登录 | `wx.login` + `code2session` + JWT |

### 1.5 明确不做的事

- ❌ 不做室内导航、校园地图、路径规划、定位
- ❌ 不做学校教务审批流、多角色权限
- ❌ 不做公开弹幕、泛社交社区
- ❌ 不做原生 App（只做微信小程序）
- ❌ 不做短信/邮件推送（只用微信订阅消息 + 小程序内提醒）
- ❌ 不做虚拟支付（MVP 阶段）


## 第 2 章 技术栈与架构

### 2.1 小程序前端

| 项目 | 选型 |
|---|---|
| 框架 | 原生微信小程序 + TypeScript（ADR-0001，不用 uni-app） |
| 状态管理 | MobX-miniprogram 或自研 Behavior |
| UI 组件库 | WeUI + 自研组件 |
| 课表组件 | 自研 ScheduleView：今日列表为主视图 + 横向滚动周卡片（`/prototype` 验证后定稿，不用 7×12 严格网格） |
| 请求库 | `wx.request` 封装 |
| 实时通信 | `wx.connectSocket`（WSS） |
| 扫码 | `wx.scanCode({ scanType: ['barCode'] })` |
| 图片选择 | `wx.chooseMedia` |
| 图片上传 | `wx.uploadFile` |
| 分享 | `onShareAppMessage`、`onShareTimeline` |
| 订阅消息 | `wx.requestSubscribeMessage` |
| 内容安全 | `security.msgSecCheck`、`security.mediaCheckAsync`（后端调用） |
| 编译目标 | 微信小程序 |

### 2.2 后端

| 项目 | 选型 |
|---|---|
| 框架 | FastAPI（Python 3.11+） |
| ORM | SQLAlchemy 2.0 |
| 数据校验 | Pydantic v2 |
| 任务调度 | APScheduler |
| 大模型调用 | 移动云 MoMA 平台（OpenAI 兼容接口，ADR-0002；Key 到位前用 mock 适配器） |
| 数据库迁移 | Alembic |
| 认证 | 微信 code2session + JWT |
| 实时通信 | WebSocket（WSS） |
| 文件存储 | 本地文件系统（MVP），预留对象存储 |
| 图书 API | Open Library（主）、豆瓣/国家图书馆（备） |

### 2.3 数据库与缓存

| 项目 | 选型 |
|---|---|
| 主数据库 | MySQL 8（比赛资源；`JSONB`→`JSON`，UUID 主键 `CHAR(36)`，TIMESTAMP 显式 `DEFAULT CURRENT_TIMESTAMP`，见 ADR-0004） |
| 缓存 | Redis 7 |
| 消息队列 | Redis（轻量） |
| 文件存储 | 本地 `uploads/` |

### 2.4 部署

- Docker + Docker Compose
- Nginx 反向代理 + HTTPS + WSS
- 比赛提供：云主机×2、容器服务（8vCPU/32G）、对象存储 200G、MySQL×2、VPC、MoMA 模型服务（队长申请）
- 微信小程序服务器域名需备案并配置（**风险项：备案周期 1–3 周，若截止前未下来，订阅消息触达降级为站内提醒演示**）
- 开发阶段可用开发者工具”不校验合法域名”


## 第 3 章 数据模型

### 3.1 users（用户）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| wx_openid | VARCHAR(64) | 微信 openid，唯一 |
| wx_unionid | VARCHAR(64) | 微信 unionid，可空 |
| nickname | VARCHAR(50) | 昵称 |
| avatar_url | VARCHAR(500) | 头像 |
| timezone | VARCHAR(50) | 默认 Asia/Shanghai |
| created_at | TIMESTAMP | 创建时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 3.2 semesters（学期）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| name | VARCHAR(100) | 如“2026 春季学期” |
| start_date | DATE | 开始日期 |
| end_date | DATE | 结束日期 |
| total_weeks | INT | 总周数 |
| is_active | BOOLEAN | 当前学期 |

### 3.3 season_periods（时令）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| name | VARCHAR(20) | spring/summer/autumn/winter |
| start_date | DATE | 开始日期 |
| end_date | DATE | 结束日期 |

### 3.4 bell_schedules（作息模板）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| season_period_id | UUID | 外键 |
| period_number | INT | 第几节 |
| start_time | TIME | 开始时间 |
| end_time | TIME | 结束时间 |
| is_break | BOOLEAN | 是否课间休息 |

### 3.5 calendar_versions（校历版本）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| version | VARCHAR(20) | v1、v2 |
| source | VARCHAR(50) | national/local/school/manual |
| published_at | TIMESTAMP | 发布时间 |
| note | TEXT | 说明 |
| is_current | BOOLEAN | 当前版本 |

### 3.6 calendar_overrides（校历覆盖）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| version_id | UUID | 关联版本 |
| date | DATE | 日期 |
| day_type | VARCHAR(20) | holiday/workday/school_holiday/temp_cancel |
| follow_weekday | VARCHAR(10) | 调休按周几执行 |
| note | TEXT | 说明 |

### 3.7 course_templates（模板课表）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| weekday | INT | 周几 1-7 |
| period_number | INT | 第几节 |
| week_pattern | VARCHAR(50) | all/odd/even/1-8,10-16 |
| course_name | VARCHAR(100) | 课程名 |
| location | VARCHAR(100) | 地点 |
| teacher | VARCHAR(50) | 教师 |
| color | VARCHAR(20) | 颜色 |
| is_locked | BOOLEAN | 锁定 |
| textbook_id | UUID | 教材 |

### 3.8 schedule_instances（实例课表）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| date | DATE | 日期 |
| period_number | INT | 第几节 |
| start_time | TIME | 实际开始 |
| end_time | TIME | 实际结束 |
| course_name | VARCHAR(100) | 课程名 |
| location | VARCHAR(100) | 地点 |
| teacher | VARCHAR(50) | 教师 |
| template_id | UUID | 来源模板 |
| status | VARCHAR(20) | active/adjusted/cancelled |
| version_id | UUID | 课表版本 |

### 3.9 textbooks（教材）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| isbn | VARCHAR(20) | ISBN，唯一 |
| title | VARCHAR(200) | 书名 |
| author | VARCHAR(200) | 作者 |
| publisher | VARCHAR(200) | 出版社 |
| edition | VARCHAR(50) | 版次 |
| cover_url | VARCHAR(500) | 封面 URL |
| cover_local_path | VARCHAR(500) | 本地路径 |
| created_at | TIMESTAMP | 创建时间 |

### 3.10 adjustments（调整记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| instance_id | UUID | 外键 |
| user_id | UUID | 外键 |
| old_value | JSON | 调整前 |
| new_value | JSON | 调整后 |
| reason | TEXT | 原因 |
| source | VARCHAR(20) | click/nlp/feedback |
| created_at | TIMESTAMP | 时间 |

### 3.11 feedback_logs（反馈日志）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| instance_id | UUID | 外键 |
| feedback_type | VARCHAR(30) | wrong_time/wrong_holiday/wrong_week/wrong_textbook |
| description | TEXT | 描述 |
| resolved | BOOLEAN | 已处理 |
| created_at | TIMESTAMP | 时间 |

### 3.12 constraint_updates（约束更新）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| source_feedback_id | UUID | 来源反馈 |
| constraint_json | JSON | 约束 |
| applied | BOOLEAN | 已应用 |
| created_at | TIMESTAMP | 时间 |

### 3.13 schedule_versions（课表版本）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| version | VARCHAR(20) | 版本号 |
| created_by | UUID | 用户 |
| change_summary | TEXT | 变更摘要 |
| created_at | TIMESTAMP | 时间 |

### 3.14 reminders（提醒）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| instance_id | UUID | 外键，可空 |
| reminder_type | VARCHAR(30) | class_change/holiday/season_switch/task |
| trigger_time | TIMESTAMP | 触发时间 |
| status | VARCHAR(20) | pending/sent/cancelled |
| message | TEXT | 内容 |
| wx_template_id | VARCHAR(64) | 订阅消息模板 ID |
| wx_subscribe_status | VARCHAR(20) | pending/granted/denied |

### 3.15 location_photos（地点照片）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| location_name | VARCHAR(100) | 地点名 |
| photo_type | VARCHAR(20) | classroom/building |
| photo_path | VARCHAR(500) | 路径 |
| created_at | TIMESTAMP | 时间 |

### 3.16 ai_conversations（AI 对话）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| role | VARCHAR(20) | user/assistant |
| content | TEXT | 内容 |
| created_at | TIMESTAMP | 时间 |

### 3.17 shared_schedules（课表分享）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| semester_id | UUID | 外键 |
| owner_id | UUID | 分享者 |
| share_code | VARCHAR(20) | 分享码，唯一 |
| permission | VARCHAR(20) | view/comment/edit |
| expires_at | TIMESTAMP | 过期时间 |
| created_at | TIMESTAMP | 时间 |

### 3.18 schedule_members（课表成员）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| shared_schedule_id | UUID | 外键 |
| user_id | UUID | 成员 |
| role | VARCHAR(20) | viewer/commenter/editor |
| joined_at | TIMESTAMP | 加入时间 |

### 3.19 comments（协作批注）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| shared_schedule_id | UUID | 外键 |
| instance_id | UUID | 关联实例，可空 |
| user_id | UUID | 批注者 |
| content | TEXT | 内容 |
| parent_id | UUID | 父批注 |
| audit_status | VARCHAR(20) | pending/pass/reject |
| created_at | TIMESTAMP | 时间 |
| updated_at | TIMESTAMP | 更新时间 |

### 3.20 template_market（模板市场）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| author_id | UUID | 作者 |
| title | VARCHAR(100) | 名称 |
| description | TEXT | 描述 |
| category | VARCHAR(50) | season/bell/semester/constraint/scene |
| tags | JSON | 标签 |
| content | JSON | 内容 |
| cover_image | VARCHAR(500) | 封面 |
| downloads | INT | 下载次数 |
| rating_avg | DECIMAL(3,2) | 平均评分 |
| rating_count | INT | 评分人数 |
| audit_status | VARCHAR(20) | pending/pass/reject |
| is_public | BOOLEAN | 是否公开 |
| created_at | TIMESTAMP | 时间 |

### 3.21 template_downloads（模板下载记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| template_id | UUID | 外键 |
| user_id | UUID | 下载者 |
| created_at | TIMESTAMP | 时间 |

### 3.22 template_ratings（模板评分）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| template_id | UUID | 外键 |
| user_id | UUID | 评分者 |
| rating | INT | 1-5 |
| comment | TEXT | 评价 |
| created_at | TIMESTAMP | 时间 |

### 3.23 wx_subscriptions（微信订阅授权记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| template_id | VARCHAR(64) | 订阅消息模板 ID |
| granted_count | INT | 授权次数 |
| used_count | INT | 已使用次数 |
| updated_at | TIMESTAMP | 更新时间 |

### 3.24 content_audits（内容审核记录）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID | 主键 |
| user_id | UUID | 外键 |
| content_type | VARCHAR(20) | text/image |
| content_ref | VARCHAR(100) | 关联 ID |
| audit_status | VARCHAR(20) | pending/pass/reject |
| audit_result | JSON | 审核结果 |
| created_at | TIMESTAMP | 时间 |


## 第 4 章 API 接口设计

### 4.1 微信认证

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/auth/wx-login | 传入 `code`，code2session，返回 JWT |
| GET | /api/auth/me | 获取当前用户 |
| PUT | /api/auth/me | 更新昵称、头像 |

### 4.2 学期与时令

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/semesters | 创建学期 |
| GET | /api/semesters | 学期列表 |
| PUT | /api/semesters/{id} | 更新 |
| DELETE | /api/semesters/{id} | 删除 |
| POST | /api/semesters/{id}/seasons | 创建时令 |
| GET | /api/semesters/{id}/seasons | 时令列表 |
| PUT | /api/seasons/{id} | 更新时令 |
| POST | /api/seasons/{id}/bells | 创建节次 |
| GET | /api/seasons/{id}/bells | 节次列表 |
| PUT | /api/bells/{id} | 更新节次 |

### 4.3 校历

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/semesters/{id}/overrides | 添加覆盖 |
| GET | /api/semesters/{id}/overrides | 覆盖列表 |
| DELETE | /api/overrides/{id} | 删除 |
| POST | /api/semesters/{id}/holidays/sync | 同步国家节假日 |
| POST | /api/semesters/{id}/holidays/parse | AI 解析公告 |
| GET | /api/semesters/{id}/calendar-versions | 版本列表 |
| POST | /api/semesters/{id}/calendar-versions/{vid}/publish | 发布 |
| POST | /api/semesters/{id}/calendar-versions/{vid}/rollback | 回滚 |

### 4.4 模板与实例

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/semesters/{id}/templates | 创建模板 |
| GET | /api/semesters/{id}/templates | 模板列表 |
| PUT | /api/templates/{id} | 更新 |
| DELETE | /api/templates/{id} | 删除 |
| POST | /api/semesters/{id}/instances/generate | 生成实例 |
| GET | /api/semesters/{id}/instances | 实例列表 |
| PUT | /api/instances/{id} | 调整实例 |
| POST | /api/instances/{id}/lock | 锁定 |
| POST | /api/instances/{id}/unlock | 解锁 |

### 4.5 实时调整

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/instances/{id}/adjust | 调整 |
| POST | /api/instances/{id}/check-conflict | 冲突检测 |
| GET | /api/instances/{id}/adjustments | 调整历史 |
| POST | /api/instances/{id}/rollback | 回滚 |
| WS | /api/ws/schedule | 实时同步 |

### 4.6 反馈纠错

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/feedback | 提交反馈 |
| GET | /api/feedback | 反馈列表 |
| PUT | /api/feedback/{id}/resolve | 标记处理 |
| POST | /api/feedback/{id}/to-constraint | 转约束 |

### 4.7 教材

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/textbooks/scan | 传入 ISBN |
| GET | /api/textbooks | 教材列表 |
| GET | /api/textbooks/{id} | 详情 |
| PUT | /api/textbooks/{id} | 更新 |
| DELETE | /api/textbooks/{id} | 删除 |
| POST | /api/textbooks/{id}/upload-cover | 上传封面 |
| POST | /api/templates/{id}/bind-textbook | 绑定教材 |
| POST | /api/textbooks/batch-scan | 批量扫码 |

### 4.8 地点照片

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/location-photos | 上传 |
| GET | /api/location-photos | 列表 |
| GET | /api/location-photos/{id} | 详情 |
| DELETE | /api/location-photos/{id} | 删除 |

### 4.9 提醒与订阅消息

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/reminders | 创建提醒 |
| GET | /api/reminders | 列表 |
| PUT | /api/reminders/{id} | 更新 |
| DELETE | /api/reminders/{id} | 删除 |
| POST | /api/reminders/batch | 批量创建 |
| POST | /api/wechat/subscribe | 记录订阅授权 |
| POST | /api/wechat/send-subscribe | 后端发送订阅消息 |

### 4.10 AI 能力

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/ai/parse-rule | 规则解析 |
| POST | /api/ai/parse-holiday | 公告解析 |
| POST | /api/ai/suggest-adjust | 调整建议 |
| POST | /api/ai/ask | 课表问答 |
| POST | /api/ai/explain-conflict | 冲突解释 |
| POST | /api/ai/generate-notice | 通知文案 |
| POST | /api/ai/ask-book | 问书 |
| POST | /api/ai/ask-time | 问时间 |
| POST | /api/ai/ask-holiday | 问假期 |
| POST | /api/ai/generate-share-text | 分享文案 |
| GET | /api/ai/conversations | 对话历史 |

### 4.11 分享与协作

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/schedules/{id}/share | 创建分享 |
| GET | /api/schedules/shared | 我分享的 |
| GET | /api/schedules/joined | 我加入的 |
| POST | /api/schedules/join/{share_code} | 加入 |
| DELETE | /api/schedules/shared/{id} | 取消分享 |
| GET | /api/schedules/shared/{id}/members | 成员列表 |
| DELETE | /api/schedules/shared/{id}/members/{uid} | 移除成员 |

### 4.12 批注

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/comments | 创建 |
| GET | /api/comments | 列表 |
| PUT | /api/comments/{id} | 更新 |
| DELETE | /api/comments/{id} | 删除 |
| POST | /api/comments/{id}/replies | 回复 |
| GET | /api/comments/{id}/replies | 回复列表 |
| WS | /api/ws/comments | 实时通知 |

### 4.13 模板市场

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/templates/market | 列表 |
| GET | /api/templates/market/{id} | 详情 |
| POST | /api/templates/{id}/publish | 发布 |
| POST | /api/templates/{id}/unpublish | 取消发布 |
| POST | /api/templates/{id}/download | 下载 |
| POST | /api/templates/{id}/rate | 评分 |
| GET | /api/templates/my | 我发布的 |
| GET | /api/templates/downloaded | 我下载的 |

### 4.14 内容安全

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/security/check-text | 文本审核 |
| POST | /api/security/check-media | 图片审核 |

### 4.15 导出

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/export/excel | 返回下载 URL |
| GET | /api/export/ics | 返回下载 URL |


## 第 5 章 核心算法

### 5.1 实例课表生成算法

**第 1 周锚定**：第 1 周 = 学期 `start_date` 所在完整自然周（周一起算）。第 N 周 =（目标日期所在周一 − 第 1 周周一）÷ 7 + 1。单双周与周次区间匹配均基于 N。前端创建学期时软性提示"建议选周一"，不强制；若 start_date 为周中，第 1 周仍是完整自然周，仅 start_date 之前无课。

```
for each date in semester.start_date..semester.end_date:
    override = calendar_overrides.find(date, version_id)

    if override.day_type == "holiday" or "school_holiday":
        continue

    if override.day_type == "workday" and override.follow_weekday:
        weekday = parse_weekday(override.follow_weekday)
    else:
        weekday = date.weekday()

    season = season_periods.find(date)
    bells = bell_schedules.where(season_period_id=season.id)

    templates = course_templates.where(
        weekday=weekday,
        week_pattern matches current_week
    )

    for tpl in templates:
        bell = bells.where(period_number=tpl.period_number)
        if bell is null:
            continue
        create schedule_instance(
            date=date,
            period_number=tpl.period_number,
            start_time=bell.start_time,
            end_time=bell.end_time,
            course_name=tpl.course_name,
            location=tpl.location,
            teacher=tpl.teacher,
            template_id=tpl.id,
            version_id=current_version
        )
```

### 5.2 周次模式匹配

支持 `all`、`odd`、`even`、`1-8`、`1-8,10-16`。

### 5.3 实时冲突检测

检查：同一日期同一时段冲突、假期、调休、时令节次、单双周、连堂、锁定实例。

### 5.4 AI 调课建议

输入冲突信息、当前课表、用户约束，调用 LLM 返回候选方案，后端校验可行性后返回。

### 5.5 反馈纠错转约束

用户反馈“周三下午不该排数学” → AI 解析 → 生成约束 `{ type: "avoid", course: "数学", weekday: 3, period_range: "5-8" }` → 存入 `constraint_updates` → 下次生成自动应用。

### 5.6 微信扫码录书

```
用户点击扫码 → wx.scanCode({ scanType: ['barCode'] })
    ↓
获取 ISBN 字符串
    ↓
POST /api/textbooks/scan { isbn }
    ↓
后端调用 Open Library API
    ↓
成功：返回书名、作者、出版社、版次、封面 URL
      后端下载封面到本地 → 保存 textbooks
    ↓
失败：返回 need_manual → 前端引导手动输入或拍照上传
```

### 5.7 版本回滚

选择回滚到 vN → 复制 `version_id = vN` 的实例为新版本 vN+1 → 更新当前版本指针 → 记录日志 → 更新提醒。

### 5.8 微信订阅消息发送

```
APScheduler 到 trigger_time
    ↓
检查 reminders 状态
    ↓
检查 wx_subscriptions 授权次数
    ↓
调用微信 subscribeMessage.send
    ↓
更新 used_count 和 reminder.status = sent
```

**授权策略（平台约束，明确接受其缺陷）：** 一次性订阅消息每次授权只能发一条，长期订阅模板个人主体拿不到。三条模板合并为**两条**（课前/调课一条、假期/时令合并一条）。用户打开小程序的关键动线（首页、课表页、设置页）批量请求授权，并引导勾选"总是保持以上选择"；`wx_subscriptions` 记录 granted/used 计数；**额度耗尽自动降级为小程序内提醒**，UI 弱提示"打开小程序续订"。明确接受：额度耗尽当天可能收不到课前提醒，文档与演示中不隐藏此限制。

### 5.9 内容安全审核

```
用户提交批注/模板描述/昵称
    ↓
后端调用 security.msgSecCheck
    ↓
通过 → 保存并展示
不通过 → 拒绝并提示
图片 → security.mediaCheckAsync
```

### 5.10 静态节假日种子（ADR-0005）

2026 全年法定节假日与调休（国务院 2025-11 已发布）硬编码于 `scripts/seed_holidays.py`，随代码走。**运行时不调用任何外部节假日 API**（比赛环境外网不稳、免费接口无 SLA）。"AI 解析公告"保留，用于 2027 年及临时调整，解析结果落成 `calendar_overrides`，与种子数据走同一套数据路径。代价：每年年初人工更新一次种子，接受。


## 第 6 章 分阶段开发任务

**时间倒排（截止 2026-10-15，约 15 天）：** 阶段 7 已推迟二期，阶段 8 仅保留 ICS 导出。**若时间紧张的保序原则：阶段 3（核心链路）→ 3.5（AI 最小闭环）→ 5（实时调整）→ 4（扫码）→ 6（订阅提醒）。** AI 部分在 Key 到位前全部走 mock 适配器，不阻塞开发；真实 API 在阶段 6 或答辩前接入。各阶段对应的评审维度：1–2/5→技术实现；3/4→应用价值+技术实现；3.5/6→AI 编码能力运用+创新性；8→展示与文档。

### 阶段一：小程序骨架 + 微信登录（预计 1.5 天）

**任务 1.1** 初始化 uni-app + Vue3 + TS 项目
**任务 1.2** 配置 Pinia、uView Plus、请求封装
**任务 1.3** 后端 FastAPI 初始化，PostgreSQL、SQLAlchemy、Alembic
**任务 1.4** 后端：users 表 + 微信 code2session + JWT
**任务 1.5** 小程序：登录页，`wx.login` 换 token
**任务 1.6** Docker Compose：PostgreSQL + Redis + 后端

**验收：** 小程序可微信登录，Token 有效，能请求后端。

### 阶段二：学期 + 时令 + 作息（预计 1.5 天）

**任务 2.1** 后端：semesters / season_periods / bell_schedules CRUD
**任务 2.2** 小程序：学期管理页
**任务 2.3** 小程序：时令管理页
**任务 2.4** 小程序：作息模板编辑页
**任务 2.5** 小程序：作息时间轴预览

**验收：** 可创建学期、四季时令、节次时间表。

### 阶段三：校历 + 模板 + 实例生成（预计 2 天）

**任务 3.1** 后端：calendar_overrides + calendar_versions CRUD
**任务 3.2** 后端：国家节假日同步（2026 种子数据）
**任务 3.3** 后端：course_templates CRUD
**任务 3.4** 后端：实例生成算法
**任务 3.5** 小程序：校历管理页
**任务 3.6** 小程序：模板课表编辑（周视图）
**任务 3.7** 小程序：实例课表展示（日/周切换，自研 ScheduleView：今日列表 + 横向滚动周卡片）
**任务 3.8** 小程序：点击实例弹出详情
**任务 3.9** ScheduleView 原型验证（`/prototype` 独立会话，与阶段 1–2 并行）：验证今日列表信息密度与周卡片切换手感，结论合入 3.7/3.8 实现

**验收：** 生成整学期实例课表，自动跳过假期，调休正确，时令切换自动更新。

### 阶段三·五：AI 最小可见闭环（预计 1 天，对应评审维度：AI 编码能力运用、创新性）

**任务 3.5.1** 后端：`/api/ai/parse-rule` 接入 MoMA（Key 未到位前用 mock 适配器，接口一次定型）
**任务 3.5.2** 后端：`/api/ai/ask` 课表问答最小闭环
**任务 3.5.3** 小程序：AI 助手对话页，可演示"自然语言调课/问答 → 课表变化"完整动线

**验收：** demo 可演示 AI 解析课表规则并生效、AI 回答课表问题。

### 阶段四：教材 + 扫码 + 照片（预计 2 天）

**任务 4.1** 后端：textbooks CRUD + 扫码接口
**任务 4.2** 后端：Open Library API + 封面下载
**任务 4.3** 后端：location_photos CRUD
**任务 4.4** 小程序：教材管理页
**任务 4.5** 小程序：微信扫码 `wx.scanCode`
**任务 4.6** 小程序：批量扫码
**任务 4.7** 小程序：扫码失败兜底
**任务 4.8** 小程序：模板绑定教材，实例展示封面
**任务 4.9** 小程序：教室/楼栋照片上传展示

**验收：** 扫码创建教材并展示封面；模板可绑定教材；实例可看教材封面和教室照片。

### 阶段五：实时调整 + 反馈 + 版本（预计 2 天）

**任务 5.1** 后端：adjustments + schedule_versions + feedback_logs + constraint_updates
**任务 5.2** 后端：实例调整接口 + 冲突检测
**任务 5.3** 后端：反馈转约束
**任务 5.4** 后端：版本回滚
**任务 5.5** 小程序：点击调整实例
**任务 5.6** 小程序：实时冲突提示
**任务 5.7** 小程序：反馈入口
**任务 5.8** 小程序：调整历史 + 回滚
**任务 5.9** WebSocket 实时同步

**验收：** 可调整，实时检测冲突，反馈可转约束，调整有记录可回滚。

### 阶段六：AI 完整能力 + 微信订阅提醒（预计 2 天）

**任务 6.1** 后端：AI 公告解析、调课建议、冲突解释、通知文案（问书/问时间/问假期为 P2，时间不够可砍）
**任务 6.2** 后端：reminders CRUD + APScheduler
**任务 6.3** 后端：微信订阅消息发送
**任务 6.4** 小程序：AI 助手对话页
**任务 6.5** 小程序：提醒管理页
**任务 6.6** 小程序：`wx.requestSubscribeMessage` 授权

**验收：** AI 解析规则生效；AI 回答课表问题；订阅消息准时触发。

### 阶段七：分享 + 批注 + 模板市场（**二期，暂缓**）

> 个人主体小程序无法上线 UGC 类功能；数据模型与 API 设计保留备查，主体升级后启用（ADR-0003）。

**任务 7.1** 后端：shared_schedules + schedule_members
**任务 7.2** 后端：comments + 回复
**任务 7.3** 后端：template_market + downloads + ratings
**任务 7.4** 后端：内容安全审核接入
**任务 7.5** 后端：WebSocket 批注通知
**任务 7.6** 小程序：课表分享页（分享码 + 微信分享）
**任务 7.7** 小程序：加入课表页
**任务 7.8** 小程序：批注侧边栏
**任务 7.9** 小程序：模板市场列表/详情/发布/下载/评分
**任务 7.10** 小程序：我的分享/我的模板

**验收：** 可分享、加入、批注、回复、发布模板、下载、评分，内容安全审核生效。

### 阶段八：导出 + 收尾（预计 1 天）

**任务 8.1** ~~后端：Excel 导出~~（时间窗口内砍掉；如时间充裕再加回）
**任务 8.2** 后端：ICS 导出（演示"订阅到日历"，效果比 Excel 好）
**任务 8.3** 小程序：导出下载与打开
**任务 8.4** 联调、Bug 修复、UI 优化、演示数据准备（评委演示用预填学期/课表/教材种子）
**任务 8.5** 展示与文档：开发过程记录（AI Coding 赛评审"AI 编码能力运用"需要过程证据，开发期全程保留 commit/会话记录）

**验收：** ICS 可在小程序内下载并打开；演示文档齐备。


## 第 7 章 约束与注意事项

### 7.1 必须遵守

1. 时间统一 `Asia/Shanghai`
2. 实例生成可重入，不重复
3. 教材封面下载后存本地
4. 扫码失败提供手动兜底
5. API 使用 Pydantic v2 校验
6. 日期显示 `YYYY-MM-DD`
7. 时令切换自动生效
8. 每次调整记录 adjustments
9. 版本回滚保留历史
10. WebSocket 断线自动重连
11. 批注权限校验
12. 模板市场内容审核（敏感词 + 微信内容安全）
13. 分享码唯一可撤销
14. 用户 openid 唯一，JWT 鉴权
15. 图片上传限制大小和格式
16. 微信订阅消息需用户授权，记录授权次数
17. 小程序服务器域名需备案并配置 HTTPS/WSS
18. 隐私协议、用户授权说明齐全

### 7.2 代码规范

- 后端：Black + Ruff + 类型注解
- 小程序：ESLint + Prettier + `<script setup lang="ts">`
- Git：Conventional Commits
- 数据库：Alembic 迁移

### 7.3 性能要求

- 实例生成：1 学期 ≤ 3 秒
- 冲突检测：≤ 200ms
- 扫码识别：≤ 2 秒
- 页面加载：≤ 1.5 秒
- WebSocket 延迟：≤ 500ms

### 7.4 安全要求

- JWT 过期 7 天
- openid 唯一
- SQLAlchemy 参数化
- XSS 转义
- 文件白名单
- 分享码随机不可预测
- 内容安全审核


## 第 8 章 环境变量

```env
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/zhike_luopan?charset=utf8mb4
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=change-me-in-production
JWT_EXPIRE_MINUTES=10080

WX_APPID=your-wx-appid
WX_SECRET=your-wx-secret
WX_SUBSCRIBE_TEMPLATE_LESSON=your-template-id    # 课前/调课提醒
WX_SUBSCRIBE_TEMPLATE_HOLIDAY=your-template-id   # 假期/时令切换提醒

AI_BASE_URL=https://moma.cmecloud.cn/v1          # 移动云 MoMA，OpenAI 兼容
AI_API_KEY=your-moma-api-key
AI_MODEL=your-model-code                          # MoMA 控制台"订购模型管理"获取，DeepSeek/GLM Flash 档即可

BOOK_API_PRIMARY=openlibrary
BOOK_API_FALLBACK=douban

UPLOAD_DIR=./uploads
MAX_UPLOAD_SIZE_MB=10

SENSITIVE_WORDS_FILE=./config/sensitive_words.txt
```


## 第 9 章 部署说明

```bash
# 开发环境
docker compose -f docker-compose.dev.yml up

# 生产环境
docker compose -f docker-compose.prod.yml up -d

# 数据库迁移
docker compose exec backend alembic upgrade head

# 初始化种子数据
docker compose exec backend python scripts/seed_holidays.py
```

**微信小程序配置：**

1. 微信公众平台创建小程序，获取 AppID 和 Secret
2. 配置服务器域名：request、uploadFile、downloadFile、socket 合法域名
3. 申请订阅消息模板：课前提醒、调课提醒、假期提醒、时令切换
4. 配置隐私协议、用户信息授权说明
5. 开发阶段可在微信开发者工具关闭域名校验


## 第 10 章 验收清单

| 编号 | 验收项 | 优先级 |
|---|---|---|
| A01 | 微信登录，Token 有效 | P0 |
| A02 | 创建学期，设置起止日期和总周数 | P0 |
| A03 | 创建春/夏/秋/冬时令 | P0 |
| A04 | 配置每个时令第 1-N 节时间 | P0 |
| A05 | 添加校历覆盖（假期、调休、临时停课） | P0 |
| A06 | 同步 2026 国家节假日和调休 | P0 |
| A07 | 创建模板课表项 | P0 |
| A08 | 一键生成整学期实例课表 | P0 |
| A09 | 实例课表日/周视图 | P0 |
| A10 | 点击实例显示时间、地点、教师、教材封面 | P0 |
| A11 | 微信扫码 ISBN 自动创建教材并展示封面 | P1 |
| A12 | 扫码失败可手动输入/拍照 | P1 |
| A13 | 模板课表绑定教材 | P1 |
| A14 | 点击调整实例，实时冲突检测 | P1 |
| A15 | 调整记录可查看、回滚 | P1 |
| A16 | 微信订阅消息课前提醒 | P1 |
| A17 | 时令切换提醒 | P1 |
| A18 | 节假日/调休提醒 | P1 |
| A19 | AI 规则解析 | P1 |
| A20 | AI 课表问答 | P1 |
| A21 | AI 调课建议 | P1 |
| A22 | AI 冲突解释 | P1 |
| A23 | 反馈纠错转约束 | P1 |
| A24 | 教室/楼栋照片上传展示 | P1 |
| A25 | 课表分享（分享码 + 微信分享） | P1（二期） |
| A26 | 加入分享的课表 | P1（二期） |
| A27 | 协作批注（发表、回复） | P1（二期） |
| A28 | 模板市场浏览、搜索、筛选 | P1（二期） |
| A29 | 发布模板到市场 | P1（二期） |
| A30 | 下载模板并一键导入 | P1（二期） |
| A31 | 模板评分与评价 | P2（二期） |
| A32 | 批量扫码录入教材 | P2 |
| A33 | 版本对比与回滚 | P2 |
| A34 | 导出 Excel | P2（本期砍掉，时间充裕再加回） |
| A35 | 导出 ICS | P2 |
| A36 | WebSocket 实时同步 | P2 |
| A37 | AI 生成通知文案 | P2 |
| A38 | AI 问书、问时间、问假期 | P2 |
| A39 | AI 生成分享文案 | P2 |
| A40 | 内容安全审核生效 | P2（二期） |


## 附：提交给 ZCode 的操作步骤

本文档即 `project-spec.md` v4.1，位于项目根目录；`CONTEXT.md`（术语表）与 `docs/adr/`（5 份 ADR）已就位。后续路径：

1. **`/to-spec`**：把本文档转成正式 spec，补充 AI Coding 赛五维评审对应关系
2. **`/to-tickets`**：拆 tracer-bullet 票，阶段 3.5 作为独立票排在阶段 3 之后、阶段 4 之前
3. **ScheduleView 原型**：`/handoff` 开独立会话跑 `/prototype`，与骨架票并行，结论在课表票开工前合入
4. 每张票用 **`/implement`** 构建（内部驱动 `/tdd`，收尾 `/code-review`），票间 `/clear`

---

**你需要提前准备：**

1. 微信小程序 AppID 和 Secret
2. 微信订阅消息模板 ID（课前、调课、假期、时令）
3. 已备案的 HTTPS/WSS 服务器域名
4. 微信开发者工具
5. HBuilderX 或 uni-app CLI

这版 v4.0 已经完全适配微信小程序，之前聊过的功能全部保留，导航已砍掉，扫码改用微信原生能力，提醒改用订阅消息。ZCode 拿到即可开发。