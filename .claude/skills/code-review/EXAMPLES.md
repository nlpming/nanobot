# 审查示例

## 示例：发现 N+1 查询

**问题代码：**
```python
for user in users:
    orders = db.query(f"SELECT * FROM orders WHERE user_id={user.id}")
```

**审查意见（🔴 严重）：**
> 循环内执行数据库查询，100 个用户将产生 101 次查询。
> 建议改为 JOIN 或 IN 查询一次性获取所有数据。

**修复方案：**
```python
user_ids = [u.id for u in users]
orders = db.query("SELECT * FROM orders WHERE user_id = ANY(%s)", [user_ids])
```

---

## 示例：输出格式

```
## 代码审查报告：src/auth/login.py

🔴 严重问题（1）
- 第 42 行：密码以明文存储，需使用 bcrypt 哈希

🟡 改进建议（2）
- 第 15 行：login() 函数超过 80 行，建议拆分
- 第 67 行：捕获了 Exception 基类，过于宽泛

🟢 做得好（1）
- JWT 过期时间设置合理（24h）
```
