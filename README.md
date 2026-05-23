# JNC Notifications Pipeline

Python pipeline for auditing notifications related to JNC case files. It processes case reports, normalizes expected notifications, matches them against certified email reports, and stores manual audit reviews as a formal input to the workflow.

## Sensitive Data Notice

This project may involve sensitive personal and medical information. This repository must not contain real data, original files, exported databases, certified email reports, PDF evidence, patient names, identification numbers, medical opinions, diagnoses, credentials, tokens, API keys, or connection strings.

Operational data must only be stored in authorized systems such as SharePoint and Azure SQL Database, applying access control, traceability, encryption, and the principle of least privilege.

## Objective

Build an auditable pipeline to:

- Consolidate qualified case reports from Excel files.
- Convert wide room/sala reports into tidy tables.
- Process certified email reports by date range.
- Identify expected notifications not found.
- Detect notifications sent outside the allowed period.
- Register manual reviews as pipeline inputs.
- Store results in Azure SQL.
- Expose SQL views for Excel and Power BI.

## Architecture

```text
SharePoint
↓
Power Automate Premium
↓
Azure Function App - Python
↓
Azure SQL Database
↓
Excel / Power BI
