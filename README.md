# document-parser-api

文档解析 API 服务（V1）项目目录已初始化。

## 快速说明
- 开发基线：`docs/V1-开发基线.md`
- 架构决策：`docs/DECISIONS.md`

## 当前状态
- [x] 目录结构初始化
- [x] V1 范围与里程碑固化
- [x] 决策日志机制建立
- [ ] API 与任务链路代码实现

## 下一步（建议）
1. 创建 `requirements.txt`
2. 创建 `docker-compose.yml`
3. 先实现 4 个核心接口骨架
4. 接入 Celery 任务状态流转
5. 接入 LlamaIndex 解析与结果落库
