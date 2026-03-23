-- ============================================================================
-- Migration: Add persona / tags update tracking columns
-- Target:    [salesagent].[dbo].[customer_persona_raw]
-- Date:      2026-03-17
-- Purpose:   Track when persona text / tags were last updated and by what source
-- ============================================================================

-- persona_updated_at   : 人物側寫文字最後更新時間
-- persona_update_source: 人物側寫文字最後更新來源 (e.g. 'transcript_ingest', 'manual')
-- tags_updated_at      : 標籤最後更新時間
-- tags_update_source   : 標籤最後更新來源 (e.g. 'tag_program', 'manual')

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'customer_persona_raw' AND COLUMN_NAME = 'persona_updated_at'
)
ALTER TABLE [customer_persona_raw]
    ADD [persona_updated_at] DATETIMEOFFSET NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'customer_persona_raw' AND COLUMN_NAME = 'persona_update_source'
)
ALTER TABLE [customer_persona_raw]
    ADD [persona_update_source] NVARCHAR(100) NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'customer_persona_raw' AND COLUMN_NAME = 'tags_updated_at'
)
ALTER TABLE [customer_persona_raw]
    ADD [tags_updated_at] DATETIMEOFFSET NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'customer_persona_raw' AND COLUMN_NAME = 'tags_update_source'
)
ALTER TABLE [customer_persona_raw]
    ADD [tags_update_source] NVARCHAR(100) NULL;
GO

-- Optional index for querying recently updated personas
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_persona_updated_at' AND object_id = OBJECT_ID('customer_persona_raw')
)
CREATE NONCLUSTERED INDEX [IX_persona_updated_at]
    ON [customer_persona_raw] ([persona_updated_at] DESC)
    WHERE [persona_updated_at] IS NOT NULL;
GO

PRINT 'Migration complete: persona tracking columns added.';
GO
