# API 文档

服务地址：`http://localhost:8000`（Swagger 交互文档：`/docs`）

认证方式：除注册/登录外，所有接口需在请求头携带 `Authorization: Bearer <token>`（登录/注册时返回 JWT，默认 7 天有效）。

---

## 1. 认证

### 1.1 注册

```
POST /api/auth/register
```

请求：

```json
{
  "account": "13800138000",
  "password": "abc12345",
  "nickname": "小明"
}
```

`account` 支持手机号（11 位）或邮箱。响应：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user": { "id": 1, "nickname": "小明", "is_admin": false }
}
```

### 1.2 登录

```
POST /api/auth/login
```

请求：`{"account": "13800138000", "password": "abc12345"}`
响应：同注册。

错误：`401` 账号或密码错误；`409` 账号已注册。

---

## 2. 知识库

### 2.1 上传文档

```
POST /api/knowledge/upload
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `file` | file | 支持 `.txt` / `.md` / `.pdf` |
| `knowledge_base_id` | int | 可选，指定知识库（默认归属用户默认库） |

响应（文档创建成功，`status=processing`，后台异步向量化）：

```json
{
  "id": 5,
  "knowledge_base_id": 1,
  "name": "产品手册.txt",
  "doc_type": "txt",
  "status": "processing",
  "chunk_count": 0,
  "error_msg": "",
  "created_at": "2026-08-09T21:00:00"
}
```

### 2.2 文档列表

```
GET /api/knowledge
```

响应：`DocumentOut[]`，`status` 取值 `processing`（处理中）/ `ready`（就绪）/ `failed`（失败，见 `error_msg`）。

### 2.3 文档详情 / 状态查询

```
GET /api/knowledge/{doc_id}
```

前端通过轮询该接口获取向量化进度（处理中每 3 秒轮询一次）。

### 2.4 删除文档

```
DELETE /api/knowledge/{doc_id}
```

级联删除：先清除 Chroma 中的对应向量数据，再删除元数据与本地文件。响应：`{"ok": true}`。

### 2.5 知识库管理

```
GET  /api/knowledge/bases          # 知识库列表
POST /api/knowledge/bases          # 创建知识库 {"name": "...", "description": "..."}
```

---

## 3. 智能问答（流式，核心接口）

### 3.1 发起流式问答

```
POST /api/chat/stream
Content-Type: application/json
```

请求：

```json
{
  "session_id": null,
  "question": "文博ERP标准版多少钱一年？"
}
```

| 字段 | 说明 |
|------|------|
| `session_id` | 会话 ID；为空则自动创建新会话并返回新 ID |
| `question` | 问题内容，≤ 500 字（超出返回 422） |
| `knowledge_base_id` | 可选（多知识库路由）：指定后只在该知识库内检索；不传则全量检索并自动路由到最相关的知识库 |

响应：`Content-Type: text/event-stream`（SSE）。

**业务规则：**
- 单次提问 > 500 字 → `422`
- 每个用户每日提问上限 100 次（可配置 `DAILY_QUESTION_LIMIT`）→ 超出返回 `429`
- 检索为空（低于相似度阈值）→ 返回兜底话术，不调用 LLM、不编造

### 3.2 SSE 事件格式

每个事件由 `event: <名称>` 与 `data: <JSON>` 两行组成，事件间以空行分隔：

```
event: start
data: {"session_id": 12, "message_id": 45, "intent": "产品咨询"}

event: delta
data: {"content": "您好，文博ERP标准版定价为 "}

event: delta
data: {"content": "3999元/年"}

event: sources
data: {"sources": [{"doc_name": "公司产品介绍.txt", "excerpt": "1. 标准版（定价 3999 元/年…", "similarity": 0.6335}]}

event: followups
data: {"suggestions": ["标准版能免费试用吗？", "升级到专业版要加多少钱？"]}

event: done
data: {"message_id": 46}
```

事件类型总表：

| 事件 | 时机 | data 字段 |
|------|------|-----------|
| `start` | 流开始，先于任何文本 | `session_id` 会话ID（新会话时由服务端生成）、`message_id` 用户消息ID、`intent` 意图分类、`knowledge_base`（可选，自动路由到的知识库名称） |
| `delta` | 回答文本增量，逐块推送（可实现逐字渲染） | `content` 本次增量文本 |
| `sources` | 回答结束后 | `sources[]`：`{doc_name 来源文档, excerpt 片段摘要, similarity 相似度}` |
| `followups` | 追问建议生成后 | `suggestions[]` 2-3 条追问问题 |
| `done` | 流正常结束 | `message_id` 助手消息ID |
| `error` | 异常（LLM 超时/限流等） | `detail` 错误描述 |

**前端消费方式**：`fetch` + `ReadableStream` 手动解析（见 `frontend/src/api/client.ts` 的 `chatStream`）。要点：

1. 以空行 `\n\n` 切分事件块；
2. 解析每块的 `event:` 与 `data:` 行；
3. `delta` 事件按序拼接即完整回答，边拼边渲染实现逐字效果；
4. 支持 `AbortController` 中断（停止生成）。

---

## 4. 会话

### 4.1 会话列表

```
GET /api/sessions
```

响应（按最近更新排序）：

```json
[
  {
    "id": 12,
    "title": "文博ERP标准版多少钱一年？",
    "intent": "产品咨询",
    "created_at": "2026-08-09T21:00:00",
    "updated_at": "2026-08-09T21:01:00"
  }
]
```

### 4.2 会话详情（完整对话记录）

```
GET /api/sessions/{session_id}/messages
```

响应：

```json
[
  {
    "id": 45,
    "session_id": 12,
    "role": "user",
    "content": "文博ERP标准版多少钱一年？",
    "intent": "产品咨询",
    "sources": [],
    "followups": [],
    "is_fallback": false,
    "created_at": "2026-08-09T21:00:00"
  },
  {
    "id": 46,
    "session_id": 12,
    "role": "assistant",
    "content": "您好，文博ERP标准版定价为 **3999元/年**...",
    "intent": "产品咨询",
    "sources": [
      {
        "doc_name": "公司产品介绍.txt",
        "excerpt": "1. 标准版（定价 3999 元/年，按年订阅）…",
        "similarity": 0.6335
      }
    ],
    "followups": ["标准版能免费试用吗？", "升级到专业版要加多少钱？"],
    "is_fallback": false,
    "created_at": "2026-08-09T21:00:05"
  }
]
```

### 4.3 消息反馈（点赞/踩）

```
POST /api/sessions/messages/{message_id}/feedback
```

请求：

```json
{
  "feedback_type": "like",
  "text": "回答很准确"
}
```

`feedback_type`：`like` / `dislike`；`text` 选填（≤500 字）。同一消息重复提交覆盖原反馈。响应：`{"ok": true}`。

---

## 5. 管理后台

### 5.1 统计总览

```
GET /api/admin/stats
```

要求 `is_admin=true`（否则 403）。响应：

```json
{
  "total_users": 3,
  "total_sessions": 8,
  "total_messages": 30,
  "total_documents": 3,
  "feedback_counts": { "like": 5, "dislike": 1 },
  "daily_stats": [
    { "date": "2026-08-03", "question_count": 0 },
    { "date": "2026-08-09", "question_count": 12 }
  ]
}
```

`daily_stats` 为近 7 日每日问答量（供折线图使用）。

### 5.2 全量会话记录（管理员）

```
GET /api/admin/sessions
```

返回所有用户的会话列表（按最近更新倒序，上限 500 条），含用户信息、意图、消息数与最近提问：

```json
[
  {
    "id": 12,
    "user": { "id": 1, "nickname": "管理员", "account": "13800000000" },
    "title": "文博ERP标准版多少钱一年？",
    "intent": "产品咨询",
    "message_count": 4,
    "last_question": "文博ERP标准版多少钱一年？",
    "created_at": "2026-08-09T21:00:00",
    "updated_at": "2026-08-09T21:01:00"
  }
]
```

### 5.3 全量会话详情（管理员）

```
GET /api/admin/sessions/{session_id}/messages
```

管理员视角查看任意用户的完整对话记录，响应结构与 `GET /api/sessions/{id}/messages` 一致。

---

## 6. 长期记忆

### 6.1 我的记忆（画像 + 情景记忆）

```
GET /api/memory
```

响应：

```json
{
  "profiles": [
    { "key": "company_size", "value": "20人", "updated_at": "2026-08-10T00:00:00" },
    { "key": "industry", "value": "电商", "updated_at": "2026-08-10T00:00:00" }
  ],
  "memories": [
    {
      "id": 3,
      "memory_type": "preference",
      "content": "用户不喜欢邮件通知，只用短信通知",
      "importance": 4,
      "created_at": "2026-08-10T00:00:00"
    }
  ]
}
```

说明：记忆由系统在每次问答后异步从对话中提取（L1 原子记忆），画像为结构化 KV（L3，Upsert+冲突检测）；情景记忆按 user_id 硬隔离。

### 6.2 遗忘记忆（遗忘机制）

```
DELETE /api/memory/{memory_id}
```

软删除（is_active=false）+ 向量侧同步清除。响应：`{"ok": true}`。

---

## 7. 通用错误码

| 状态码 | 含义 |
|--------|------|
| 400 | 参数不合法（如不支持的文件格式） |
| 401 | 未登录 / 凭证失效 |
| 403 | 无权限（非管理员访问后台） |
| 404 | 资源不存在 |
| 409 | 账号已注册 |
| 422 | 校验失败（如问题超 500 字） |
| 429 | 触发每日提问上限 |
| 500 | 服务端错误（LLM 异常时流内会先发 `error` 事件） |
