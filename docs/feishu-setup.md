# nanobot 接入飞书（Feishu/Lark）

## 工作原理

nanobot 通过飞书的 **WebSocket 长连接**接收消息，无需公网 IP 或 Webhook。

---

## 第一步：创建飞书应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app)，点击「创建企业自建应用」
2. 进入应用后，左侧菜单 → **添加应用能力** → 勾选 **机器人**
3. 配置**权限管理**，开通以下权限：

   | 权限标识 | 说明 | 是否必须 |
   |----------|------|----------|
   | `im:message` | 发送消息 | ✅ |
   | `im:message.p2p_msg:readonly` | 接收私聊消息 | ✅ |
   | `im:message.group_msg:readonly` | 接收群聊消息 | 群聊时需要 |
   | `cardkit:card:write` | 创建并更新卡片（流式回复） | 建议开启 |

   > 如果无法申请 `cardkit:card:write`，在 config 中设置 `"streaming": false`，机器人仍可正常工作，只是回复不支持逐字流式输出。

4. 配置**事件订阅**：
   - 添加事件：`im.message.receive_v1`（接收消息）
   - 加密策略：选择**长连接**模式（无需填写 Request URL）
   
   > 长连接模式需要先运行 nanobot 才能在控制台完成订阅确认。

5. 获取凭证：左侧菜单 → **凭证与基础信息** → 复制 **App ID** 和 **App Secret**

6. 发布应用版本（每次修改权限后需重新发布）

---

## 第二步：配置 nanobot

编辑 `~/.nanobot/config.json`，添加 `feishu` 配置：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxxxxxxxxx",
      "appSecret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "encryptKey": "",
      "verificationToken": "",
      "allowFrom": ["ou_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
      "groupPolicy": "mention",
      "replyToMessage": false,
      "streaming": true
    }
  }
}
```

### 配置字段说明

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 启用飞书频道 |
| `appId` | string | `""` | 飞书应用的 App ID |
| `appSecret` | string | `""` | 飞书应用的 App Secret |
| `encryptKey` | string | `""` | 消息加密密钥，长连接模式下可留空 |
| `verificationToken` | string | `""` | 验证 token，长连接模式下可留空 |
| `allowFrom` | list | `[]` | 允许的用户 open_id 白名单；填 `["*"]` 表示允许所有用户 |
| `groupPolicy` | string | `"mention"` | 群聊响应策略：`"mention"`（仅@时响应）或 `"open"`（响应所有消息） |
| `replyToMessage` | bool | `false` | 回复时是否引用用户原消息 |
| `streaming` | bool | `true` | 是否启用 CardKit 流式回复（需要 `cardkit:card:write` 权限） |

### 如何获取 `allowFrom` 中的 open_id

启动 nanobot 后，用飞书账号向机器人发送任意消息，在终端日志中会打印出发送者的 open_id，格式为 `ou_xxxxxxxx`，复制填入即可。

---

## 第三步：启动

```bash
nanobot gateway
```

飞书通道启动后会自动建立 WebSocket 长连接，终端日志中可见：
```
INFO  Feishu channel started
```

---

## 流式回复（CardKit Streaming）

`streaming: true` 时，nanobot 使用飞书 CardKit API 实现逐字流式回复：

1. 第一个 delta 到达时创建一张 CardKit 卡片并发送到会话
2. 后续 delta 通过 `card.stream_update` API 更新卡片内容（节流间隔 0.5 秒）
3. 输出完成后调用 `card.settings` 关闭 `streaming_mode`，消除会话列表中的"生成中"占位符

若不满足权限或创建卡片失败，自动降级为普通消息发送。

---

## 多实例部署（同时运行多个频道）

如需为飞书单独维护一个实例（独立 workspace 和配置）：

```bash
# 初始化专属配置
nanobot onboard --config ~/.nanobot-feishu/config.json --workspace ~/.nanobot-feishu/workspace

# 启动（指定端口避免冲突）
nanobot gateway --config ~/.nanobot-feishu/config.json --port 18792
```

---

## 常见问题

**Q：事件订阅页面要求填写 Request URL，填什么？**
选择「使用长连接接收事件」模式，不需要填写 URL，也不需要公网 IP。

**Q：机器人在群里不回复消息？**
检查 `groupPolicy` 配置：默认为 `"mention"`，需要 @机器人 才会响应。改为 `"open"` 则响应所有群消息。

**Q：流式回复不生效，回复整块出现？**
确认已申请 `cardkit:card:write` 权限并发布新版本。也可以设置 `"streaming": false` 禁用流式，改用普通卡片回复。

**Q：`allowFrom` 如何配置才安全？**
不要使用 `["*"]`（允许所有人）部署在生产环境。通过日志获取自己的 open_id 后填入白名单。
