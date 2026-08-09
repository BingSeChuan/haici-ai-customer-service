# 前端 — React + TypeScript

企业级 LLM 智能客服系统前端：SSE 流式逐字对话、知识库管理、会话历史、用户反馈、管理后台。

## 技术栈

- React 19 + TypeScript + Vite
- 无 UI 框架依赖，手写样式；流式渲染使用 fetch + ReadableStream 手写 SSE 解析

## 启动步骤

```bash
npm install
npm run dev
```

默认访问 http://localhost:5173 ，后端地址通过 `VITE_API_BASE` 配置（默认 `http://localhost:8000`）：

```bash
# 如需修改后端地址
VITE_API_BASE=http://localhost:8000 npm run dev
```

## 页面

| 页面 | 说明 |
|------|------|
| 登录 / 注册 | 手机号或邮箱 + 密码，JWT 认证 |
| 智能对话 | SSE 流式逐字回答、引用来源卡片、意图徽标、追问建议、点赞/踩反馈、多会话 |
| 知识库 | 上传 .txt/.md/.pdf，状态轮询（处理中/就绪/失败），删除联动清向量 |
| 管理后台 | 全量统计（用户/会话/消息/文档）、反馈分布、近 7 日问答量折线图 |

## 目录结构

```
src/
├── api/
│   ├── client.ts    # fetch 封装 + SSE 流式解析（ReadableStream）
│   └── types.ts     # 接口类型
├── pages/
│   ├── LoginPage.tsx
│   ├── ChatPage.tsx     # 核心：流式对话
│   ├── KnowledgePage.tsx
│   ├── MemoryPage.tsx   # 长期记忆 / 画像
│   └── AdminPage.tsx
├── App.tsx              # 布局 + 导航
└── index.css
```
