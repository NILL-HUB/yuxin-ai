// 记忆系统 TKG schema 初始化脚本
// Neo4j 5.x 语法，幂等可重复执行
// 执行方式: cat neo4j_init.cypher | cypher-shell -u neo4j -p <password>
// 或在 Neo4j Browser 中粘贴执行

// ==================== 约束 ====================

CREATE CONSTRAINT episode_node_id_unique IF NOT EXISTS FOR (n:Episode) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT entity_node_id_unique IF NOT EXISTS FOR (n:Entity) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT entity_name_user_unique IF NOT EXISTS FOR (n:Entity) REQUIRE (n.name, n.user_id) IS UNIQUE;
CREATE CONSTRAINT memorynode_id_unique IF NOT EXISTS FOR (n:MemoryNode) REQUIRE n.id IS UNIQUE;

// ==================== 索引 ====================

CREATE INDEX episode_user_id_idx IF NOT EXISTS FOR (n:Episode) ON (n.user_id);
CREATE INDEX episode_tier_idx IF NOT EXISTS FOR (n:Episode) ON (n.tier);
CREATE INDEX episode_created_at_idx IF NOT EXISTS FOR (n:Episode) ON (n.created_at);
CREATE INDEX episode_is_active_idx IF NOT EXISTS FOR (n:Episode) ON (n.is_active);
CREATE INDEX entity_user_id_idx IF NOT EXISTS FOR (n:Entity) ON (n.user_id);
CREATE INDEX entity_tier_idx IF NOT EXISTS FOR (n:Entity) ON (n.tier);
CREATE INDEX memorynode_user_id_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.user_id);
CREATE INDEX memorynode_storage_tier_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.storage_tier);
CREATE INDEX memorynode_is_active_idx IF NOT EXISTS FOR (n:MemoryNode) ON (n.is_active);

// ==================== 全文索引 ====================

CREATE FULLTEXT INDEX memoryFullText IF NOT EXISTS FOR (n:MemoryNode) ON EACH [n.content];
CREATE FULLTEXT INDEX entityFullText IF NOT EXISTS FOR (n:Entity) ON EACH [n.name, n.summary];

// ==================== 验证 ====================
// SHOW CONSTRAINTS;
// SHOW INDEXES;
