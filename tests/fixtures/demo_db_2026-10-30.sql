-- AgroShield demo database as of 30 October 2026 (before migrations): fictional people only, created by
-- agroshield-portal demo with development keys. Used by tests/test_migrations.py.
BEGIN TRANSACTION;
CREATE TABLE audit_event (
	id INTEGER NOT NULL, 
	at DATETIME NOT NULL, 
	actor VARCHAR(60) NOT NULL, 
	action VARCHAR(60) NOT NULL, 
	entity VARCHAR(40) NOT NULL, 
	entity_id VARCHAR(40), 
	details JSON NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "audit_event" VALUES(1,'2026-10-29 22:35:35.834895','demo-manager','farmer.created','farmer','a78772c762ee43d89d48124867dc972f','{"member_no": "D-0001", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(2,'2026-10-29 22:35:35.848705','demo-manager','policy.created','policy','8b7fe3c205944dda97e2c83aa866a340','{"policy_no": "AGS-DEMO-LR27-00001", "layers": "B", "gross_kes": 3768.1, "farmer_pays_kes": 1752.17, "quote_id": "Q-20261029-e2e30043", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(3,'2026-10-29 22:35:35.860706','demo-manager','farmer.created','farmer','60c86eab900044269448bfc32fc33c98','{"member_no": "D-0002", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(4,'2026-10-29 22:35:35.865706','demo-manager','policy.created','policy','38034213c61a4f8e853956b81ad0d092','{"policy_no": "AGS-DEMO-LR27-00002", "layers": "B", "gross_kes": 6594.18, "farmer_pays_kes": 3198.18, "quote_id": "Q-20261029-e6eb915b", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(5,'2026-10-29 22:35:35.872838','demo-manager','farmer.created','farmer','1397f4913ee9466aba5bce95da0189f6','{"member_no": "D-0003", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(6,'2026-10-29 22:35:35.885948','demo-manager','policy.created','policy','ca3c309229b24a149f9c67680d57d750','{"policy_no": "AGS-DEMO-LR27-00003", "layers": "B", "gross_kes": 1759.76, "farmer_pays_kes": 879.88, "quote_id": "Q-20261029-7412656b", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(7,'2026-10-29 22:35:35.887949','demo-manager','farmer.created','farmer','d2dbe41a49af4edb8fbd37926140de6d','{"member_no": "D-0004", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(8,'2026-10-29 22:35:35.897951','demo-manager','policy.created','policy','d8a11ccf7812418d809dfe1b8bcf400d','{"policy_no": "AGS-DEMO-LR27-00004", "layers": "B", "gross_kes": 8478.23, "farmer_pays_kes": 4069.55, "quote_id": "Q-20261029-4dbf9759", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(9,'2026-10-29 22:35:35.901949','demo-manager','farmer.created','farmer','85296c3b3d25486f982860996cf0383c','{"member_no": "D-0005", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(10,'2026-10-29 22:35:35.912949','demo-manager','policy.created','policy','c171f6893b4e41ccbedcf016ec8237f7','{"policy_no": "AGS-DEMO-LR27-00005", "layers": "B", "gross_kes": 942.03, "farmer_pays_kes": 471.01, "quote_id": "Q-20261029-6e95f9be", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(11,'2026-10-29 22:35:35.916440','demo-manager','farmer.created','farmer','a568f3f6b128464692c229804a6ffdcd','{"member_no": "D-0006", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(12,'2026-10-29 22:35:35.921141','demo-manager','policy.created','policy','7dfc27a0a10a4a67a7819e8e33198d79','{"policy_no": "AGS-DEMO-LR27-00006", "layers": "B", "gross_kes": 9420.25, "farmer_pays_kes": 4474.61, "quote_id": "Q-20261029-800d472c", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(13,'2026-10-29 22:35:35.921141','demo-manager','bulk.committed','sacco','1','{"rows": 6, "file_sha256": "37c62e47ebc35969cc8b8188a5211ddf5b970b5cb9a933abe096c71f16f16ae5"}');
INSERT INTO "audit_event" VALUES(14,'2026-10-29 22:35:35.921141','demo-manager','payment.recorded','policy','8b7fe3c205944dda97e2c83aa866a340','{"policy_no": "AGS-DEMO-LR27-00001", "method": "sacco_deduction", "amount_kes": 1753.0, "within_window": true, "status": "active", "paid_kes": 1753.0}');
INSERT INTO "audit_event" VALUES(15,'2026-10-29 22:35:35.921141','demo-manager','mpesa.stk_requested','policy','38034213c61a4f8e853956b81ad0d092','{"policy_no": "AGS-DEMO-LR27-00002", "amount_kes": 1599, "environment": "simulated"}');
INSERT INTO "audit_event" VALUES(16,'2026-10-29 22:35:35.932911','mpesa','payment.recorded','policy','38034213c61a4f8e853956b81ad0d092','{"policy_no": "AGS-DEMO-LR27-00002", "method": "mpesa", "amount_kes": 1599.0, "within_window": true, "status": "pending_payment", "paid_kes": 1599.0}');
INSERT INTO "audit_event" VALUES(17,'2026-10-29 22:35:35.935956','demo-manager','mpesa.stk_requested','policy','ca3c309229b24a149f9c67680d57d750','{"policy_no": "AGS-DEMO-LR27-00003", "amount_kes": 880, "environment": "simulated"}');
INSERT INTO "audit_event" VALUES(18,'2026-10-29 22:35:35.937956','demo-manager','payment.recorded','policy','d8a11ccf7812418d809dfe1b8bcf400d','{"policy_no": "AGS-DEMO-LR27-00004", "method": "sacco_deduction", "amount_kes": 1000.0, "within_window": true, "status": "pending_payment", "paid_kes": 1000.0}');
INSERT INTO "audit_event" VALUES(19,'2026-10-29 22:35:35.949920','demo-manager','policy.created','policy','08353011bfc84f8eb328ebc7eedc5ac4','{"policy_no": "AGS-DEMO-LR08-00007", "layers": "B", "gross_kes": 3768.1, "farmer_pays_kes": 1752.17, "quote_id": "Q-20261029-8f267586", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(20,'2026-10-29 22:35:35.955069','demo-manager','policy.created','policy','5eb2801dcd404067a835489b9e1640a7','{"policy_no": "AGS-DEMO-LR08-00008", "layers": "B", "gross_kes": 6594.18, "farmer_pays_kes": 3198.18, "quote_id": "Q-20261029-7c267b01", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(21,'2026-10-29 22:35:35.955069','demo-manager','policy.created','policy','dbda1916ed4749479ac80032900bf864','{"policy_no": "AGS-DEMO-LR08-00009", "layers": "B", "gross_kes": 1759.76, "farmer_pays_kes": 879.88, "quote_id": "Q-20261029-6f7b9590", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(22,'2026-10-29 22:35:35.971613','demo-manager','policy.created','policy','d6aff0dab313420e8a3157b56aa3bf06','{"policy_no": "AGS-DEMO-LR08-00010", "layers": "B", "gross_kes": 8478.23, "farmer_pays_kes": 4069.55, "quote_id": "Q-20261029-1f3b41e6", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(23,'2026-10-29 22:35:35.971613','demo-manager','bulk.committed','sacco','1','{"rows": 4, "file_sha256": "dc7df2aa2c10c11959c82ea96132b5c577cc87a60b22d21375dd5c75d0e4d425"}');
INSERT INTO "audit_event" VALUES(24,'2026-10-29 22:35:35.971613','demo-manager','payment.recorded','policy','08353011bfc84f8eb328ebc7eedc5ac4','{"policy_no": "AGS-DEMO-LR08-00007", "method": "sacco_deduction", "amount_kes": 1753.0, "within_window": true, "status": "active", "paid_kes": 1753.0}');
INSERT INTO "audit_event" VALUES(25,'2026-10-29 22:35:35.971613','demo-manager','payment.recorded','policy','5eb2801dcd404067a835489b9e1640a7','{"policy_no": "AGS-DEMO-LR08-00008", "method": "sacco_deduction", "amount_kes": 3199.0, "within_window": true, "status": "active", "paid_kes": 3199.0}');
INSERT INTO "audit_event" VALUES(26,'2026-10-29 22:35:35.971613','demo-manager','payment.recorded','policy','dbda1916ed4749479ac80032900bf864','{"policy_no": "AGS-DEMO-LR08-00009", "method": "sacco_deduction", "amount_kes": 880.0, "within_window": true, "status": "active", "paid_kes": 880.0}');
INSERT INTO "audit_event" VALUES(27,'2026-10-29 22:35:35.971613','system','policy.lapsed_unpaid','policy','d6aff0dab313420e8a3157b56aa3bf06','{"policy_no": "AGS-DEMO-LR08-00010", "paid_kes": 0.0}');
INSERT INTO "audit_event" VALUES(28,'2026-10-29 22:35:36.143942','monitor','trigger.calculated','ward_status','1','{"ward": "ward-a", "season": "LR", "year": 2008, "mode": "replay", "phase": "in_season", "level": "normal", "confirmed": [], "index_versions": "B-1.2.0", "source_sha256": "7f0740519698016a4e8929964c4802435591076820c2773de164829c901bb568", "file_sha256": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}');
INSERT INTO "audit_event" VALUES(29,'2026-10-29 22:35:36.213919','monitor','trigger.calculated','ward_status','2','{"ward": "ward-a", "season": "LR", "year": 2008, "mode": "replay", "phase": "in_season", "level": "watch", "confirmed": [], "index_versions": "B-1.2.0", "source_sha256": "ac4528d5e62dd8b27a32e4decbd2b172543c7cedc49a2d10ebe42cf1b5d3b3d2", "file_sha256": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}');
INSERT INTO "audit_event" VALUES(30,'2026-10-29 22:35:36.214918','monitor','trigger.calculated','ward_status','3','{"ward": "ward-a", "season": "LR", "year": 2008, "mode": "replay", "phase": "complete", "level": "payout", "confirmed": ["wrsi_final"], "index_versions": "B-1.2.0", "source_sha256": "a1e8aa7a91a133911c590e8335b7ebbd67e63a8f1dad319495feff528d2238c2", "file_sha256": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}');
INSERT INTO "audit_event" VALUES(31,'2026-10-29 22:35:36.427394','monitor','payout.calculated','policy','08353011bfc84f8eb328ebc7eedc5ac4','{"policy_no": "AGS-DEMO-LR08-00007", "kind": "wrsi", "amount_kes": 8280.0, "index_versions": "B-1.2.0", "ward_status": 3}');
INSERT INTO "audit_event" VALUES(32,'2026-10-29 22:35:36.427394','monitor','payout.calculated','policy','5eb2801dcd404067a835489b9e1640a7','{"policy_no": "AGS-DEMO-LR08-00008", "kind": "wrsi", "amount_kes": 14490.0, "index_versions": "B-1.2.0", "ward_status": 3}');
INSERT INTO "audit_event" VALUES(33,'2026-10-29 22:35:36.427394','monitor','payout.calculated','policy','dbda1916ed4749479ac80032900bf864','{"policy_no": "AGS-DEMO-LR08-00009", "kind": "wrsi", "amount_kes": 3105.0, "index_versions": "B-1.2.0", "ward_status": 3}');
INSERT INTO "audit_event" VALUES(34,'2026-10-29 22:35:36.429294','demo-underwriter','payout.approved','policy','08353011bfc84f8eb328ebc7eedc5ac4','{"policy_no": "AGS-DEMO-LR08-00007", "kind": "wrsi", "amount_kes": 8280.0}');
INSERT INTO "audit_event" VALUES(35,'2026-10-29 22:35:36.432928','demo-underwriter','payout.approved','policy','5eb2801dcd404067a835489b9e1640a7','{"policy_no": "AGS-DEMO-LR08-00008", "kind": "wrsi", "amount_kes": 14490.0}');
INSERT INTO "audit_event" VALUES(36,'2026-10-29 22:35:36.433973','demo-manager','payout.paid','policy','08353011bfc84f8eb328ebc7eedc5ac4','{"policy_no": "AGS-DEMO-LR08-00007", "kind": "wrsi", "method": "mpesa", "amount_kes": 8280.0, "days_late": 6623}');
INSERT INTO "audit_event" VALUES(37,'2026-10-29 22:35:36.437971','demo-manager','farmer.created','farmer','585fa9aa8d7e40cab55dbc201bb1897c','{"member_no": "M-0001", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(38,'2026-10-29 22:35:36.442992','demo-manager','policy.created','policy','4287ffcd4767475b8ac915149e90ed81','{"policy_no": "AGS-DEMO2-LR27-00001", "layers": "B", "gross_kes": 5652.15, "farmer_pays_kes": 2684.77, "quote_id": "Q-20261029-cdee2edf", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(39,'2026-10-29 22:35:36.445127','demo-manager','farmer.created','farmer','19d17f7f5cbe47758370752962744e4c','{"member_no": "M-0002", "ward": "ward-a", "channel": "csv"}');
INSERT INTO "audit_event" VALUES(40,'2026-10-29 22:35:36.449214','demo-manager','policy.created','policy','60121f393b2a4e108e57beb18c70d74c','{"policy_no": "AGS-DEMO2-LR27-00002", "layers": "B", "gross_kes": 6548.4, "farmer_pays_kes": 3274.2, "quote_id": "Q-20261029-e7425e7c", "channel": "csv", "index_versions": {"layer_b": "B-1.2.0"}}');
INSERT INTO "audit_event" VALUES(41,'2026-10-29 22:35:36.451217','demo-manager','bulk.committed','sacco','2','{"rows": 2, "file_sha256": "24a0128e7b949cbf1810692268969578594d7a73022c4e09963371717d1d7989"}');
INSERT INTO "audit_event" VALUES(42,'2026-10-29 22:35:36.454212','demo-manager','remittance.recorded','premium_remittance','RM-5C38FC','{"amount_kes": 5000.0, "remitted_on": "2026-10-30", "method": "bank_transfer", "reference": "DEMO-BANK-0001", "sacco": "DEMO"}');
INSERT INTO "audit_event" VALUES(43,'2026-10-29 22:35:41.700992','monitor','trigger.calculated','ward_status','4','{"ward": "ward-a", "season": "LR", "year": 2027, "mode": "live", "phase": "before_season", "level": "none", "confirmed": [], "index_versions": "B-1.2.0", "source_sha256": null, "file_sha256": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}');
INSERT INTO "audit_event" VALUES(44,'2026-10-29 22:35:41.700992','monitor','trigger.calculated','ward_status','5','{"ward": "ward-b", "season": "LR", "year": 2026, "mode": "live", "phase": "data_unavailable", "level": "none", "confirmed": [], "index_versions": "B-1.2.0", "source_sha256": null, "file_sha256": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}');
INSERT INTO "audit_event" VALUES(45,'2026-10-29 22:39:21.660630','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(46,'2026-10-29 22:39:27.218998','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(47,'2026-10-29 22:39:39.915566','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(48,'2026-10-29 22:39:53.051818','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(49,'2026-10-29 22:40:04.653344','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(50,'2026-10-29 22:40:16.217390','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(51,'2026-10-29 22:40:27.947372','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(52,'2026-10-29 22:40:39.394033','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(53,'2026-10-29 22:40:51.448284','demo-officer','login','officer','3','{}');
INSERT INTO "audit_event" VALUES(54,'2026-10-29 22:41:03.625574','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(55,'2026-10-29 22:41:06.250109','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(56,'2026-10-29 22:41:23.981407','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(57,'2026-10-29 22:41:41.673736','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(58,'2026-10-29 22:41:59.226716','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(59,'2026-10-29 22:42:16.575821','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(60,'2026-10-29 22:42:34.049852','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(61,'2026-10-29 22:42:51.339785','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(62,'2026-10-29 22:43:10.003703','demo-manager','login','officer','2','{}');
INSERT INTO "audit_event" VALUES(63,'2026-10-29 22:43:28.654222','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(64,'2026-10-29 22:43:31.865441','demo-underwriter','portfolio.exported','insurer','DEMOUW','{"season": "all", "sacco": "all"}');
INSERT INTO "audit_event" VALUES(65,'2026-10-29 22:43:32.063453','demo-underwriter','remittance.exported','premium_remittance','DEMOUW','{}');
INSERT INTO "audit_event" VALUES(66,'2026-10-29 22:43:32.685483','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(67,'2026-10-29 22:43:44.495737','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(68,'2026-10-29 22:43:56.631041','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(69,'2026-10-29 22:44:08.388730','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(70,'2026-10-29 22:44:20.698248','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(71,'2026-10-29 22:44:32.762015','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(72,'2026-10-29 22:44:44.871160','demo-underwriter','login','officer','1','{}');
INSERT INTO "audit_event" VALUES(73,'2026-10-29 22:44:58.146420','demo-underwriter','login','officer','1','{}');
CREATE TABLE consent (
	id INTEGER NOT NULL, 
	farmer_id VARCHAR(32) NOT NULL, 
	purpose VARCHAR(40) NOT NULL, 
	granted BOOLEAN NOT NULL, 
	wording_version VARCHAR(20) NOT NULL, 
	wording_sha256 VARCHAR(64) NOT NULL, 
	channel VARCHAR(20) NOT NULL, 
	captured_by INTEGER, 
	captured_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(farmer_id) REFERENCES farmer (id), 
	FOREIGN KEY(captured_by) REFERENCES officer (id)
);
INSERT INTO "consent" VALUES(1,'a78772c762ee43d89d48124867dc972f','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.842699');
INSERT INTO "consent" VALUES(2,'a78772c762ee43d89d48124867dc972f','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.842699');
INSERT INTO "consent" VALUES(3,'a78772c762ee43d89d48124867dc972f','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.842699');
INSERT INTO "consent" VALUES(4,'60c86eab900044269448bfc32fc33c98','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.863704');
INSERT INTO "consent" VALUES(5,'60c86eab900044269448bfc32fc33c98','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.863704');
INSERT INTO "consent" VALUES(6,'60c86eab900044269448bfc32fc33c98','loan_linked_payout',1,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.863704');
INSERT INTO "consent" VALUES(7,'1397f4913ee9466aba5bce95da0189f6','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.883948');
INSERT INTO "consent" VALUES(8,'1397f4913ee9466aba5bce95da0189f6','sms',0,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.883948');
INSERT INTO "consent" VALUES(9,'1397f4913ee9466aba5bce95da0189f6','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.883948');
INSERT INTO "consent" VALUES(10,'d2dbe41a49af4edb8fbd37926140de6d','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.894954');
INSERT INTO "consent" VALUES(11,'d2dbe41a49af4edb8fbd37926140de6d','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.894954');
INSERT INTO "consent" VALUES(12,'d2dbe41a49af4edb8fbd37926140de6d','loan_linked_payout',1,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.894954');
INSERT INTO "consent" VALUES(13,'85296c3b3d25486f982860996cf0383c','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.908949');
INSERT INTO "consent" VALUES(14,'85296c3b3d25486f982860996cf0383c','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.908949');
INSERT INTO "consent" VALUES(15,'85296c3b3d25486f982860996cf0383c','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.908949');
INSERT INTO "consent" VALUES(16,'a568f3f6b128464692c229804a6ffdcd','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.919215');
INSERT INTO "consent" VALUES(17,'a568f3f6b128464692c229804a6ffdcd','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.919215');
INSERT INTO "consent" VALUES(18,'a568f3f6b128464692c229804a6ffdcd','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.919215');
INSERT INTO "consent" VALUES(19,'a78772c762ee43d89d48124867dc972f','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.947957');
INSERT INTO "consent" VALUES(20,'a78772c762ee43d89d48124867dc972f','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.947957');
INSERT INTO "consent" VALUES(21,'a78772c762ee43d89d48124867dc972f','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.947957');
INSERT INTO "consent" VALUES(22,'60c86eab900044269448bfc32fc33c98','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.955069');
INSERT INTO "consent" VALUES(23,'60c86eab900044269448bfc32fc33c98','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.955069');
INSERT INTO "consent" VALUES(24,'60c86eab900044269448bfc32fc33c98','loan_linked_payout',1,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.955069');
INSERT INTO "consent" VALUES(25,'1397f4913ee9466aba5bce95da0189f6','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.955069');
INSERT INTO "consent" VALUES(26,'1397f4913ee9466aba5bce95da0189f6','sms',0,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.955069');
INSERT INTO "consent" VALUES(27,'1397f4913ee9466aba5bce95da0189f6','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.955069');
INSERT INTO "consent" VALUES(28,'d2dbe41a49af4edb8fbd37926140de6d','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:35.969275');
INSERT INTO "consent" VALUES(29,'d2dbe41a49af4edb8fbd37926140de6d','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:35.969275');
INSERT INTO "consent" VALUES(30,'d2dbe41a49af4edb8fbd37926140de6d','loan_linked_payout',1,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:35.969275');
INSERT INTO "consent" VALUES(31,'585fa9aa8d7e40cab55dbc201bb1897c','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:36.439973');
INSERT INTO "consent" VALUES(32,'585fa9aa8d7e40cab55dbc201bb1897c','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:36.439973');
INSERT INTO "consent" VALUES(33,'585fa9aa8d7e40cab55dbc201bb1897c','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:36.439973');
INSERT INTO "consent" VALUES(34,'19d17f7f5cbe47758370752962744e4c','data_processing',1,'C-2026-10-29','c612a72ff0db8be43bdc4e56e1392dc6d799fae0bbabc806b4d891c829600535','csv',2,'2026-10-29 22:35:36.448169');
INSERT INTO "consent" VALUES(35,'19d17f7f5cbe47758370752962744e4c','sms',1,'C-2026-10-29','48d4d08d9beb457f789cc8c34b3966156f1c0ddd6bfb1b41796a9c2d4f9c70d2','csv',2,'2026-10-29 22:35:36.448169');
INSERT INTO "consent" VALUES(36,'19d17f7f5cbe47758370752962744e4c','loan_linked_payout',0,'C-2026-10-29','86c030144c20d53aa1451570215988e14e0421c258f94455bfd067085d459df8','csv',2,'2026-10-29 22:35:36.448169');
CREATE TABLE farmer (
	id VARCHAR(32) NOT NULL, 
	sacco_id INTEGER NOT NULL, 
	member_no VARCHAR(40) NOT NULL, 
	full_name VARCHAR(120) NOT NULL, 
	national_id_enc TEXT NOT NULL, 
	national_id_hash VARCHAR(64) NOT NULL, 
	national_id_masked VARCHAR(16) NOT NULL, 
	phone_enc TEXT NOT NULL, 
	phone_hash VARCHAR(64) NOT NULL, 
	phone_masked VARCHAR(24) NOT NULL, 
	gender VARCHAR(16) NOT NULL, 
	ward_id VARCHAR(40) NOT NULL, 
	kiamis_status VARCHAR(20) NOT NULL, 
	language VARCHAR(2) NOT NULL, 
	created_by INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (sacco_id, member_no), 
	UNIQUE (sacco_id, national_id_hash), 
	FOREIGN KEY(sacco_id) REFERENCES sacco (id), 
	FOREIGN KEY(created_by) REFERENCES officer (id)
);
INSERT INTO "farmer" VALUES('a78772c762ee43d89d48124867dc972f',1,'D-0001','Wanjiku Kamau (fictional)','ow14DPFfQ7s7wED0NCX3/eEYJMF5aJNppbTaMStMufHBDr7S','4f0393bfcbcb8f7bdcea459ce4673d38bd382040a9a3767b8c3db9098107fed3','*****001','l9tuJWYXM4i0JdQDaANUPl1KET4bSKmWu+csX80+OF8ZMLFtZ246uf8=','cd28f17f25eb47a54c37ea14d53cff95c13e7a2c3a48cf65ad26375c281936b2','+254 7** *** 001','female','ward-a','not_found','sw',2,'2026-10-29 22:35:35.831895');
INSERT INTO "farmer" VALUES('60c86eab900044269448bfc32fc33c98',1,'D-0002','Kiprono Langat (fictional)','A5X/cvBdmEkEb96q/RcCjbqsFGZYKITb/fYCG2MRyhKFzGxc','f56b48b4cd4dc88362c1bdf6c0ce1300ddd45ff6d49925a2b5ee900d2c56b1c8','*****002','7/Hp7uKnrHFd3zgqeY+hywFKZUeA/EvmQlaC81u/6pfVlvLVkpGoau0=','5142e76b16fbb7673526a5dba3bbb5582cf0ad90a4604436349917e819bd3f20','+254 7** *** 002','male','ward-a','not_found','en',2,'2026-10-29 22:35:35.859706');
INSERT INTO "farmer" VALUES('1397f4913ee9466aba5bce95da0189f6',1,'D-0003','Akinyi Otieno (fictional)','H2j6He48DIiBLsYPlVzSBlqxCpJu9tAM89Lzw72zVvIYTwSZ','fdccaafc9af84ebe1a211000f4dcf0907d84724a76919474419f3d9ea7da5027','*****003','HQj99eByxFNUXeMHw4WrUEqLocEn8ImGYonWhu3+rM4EZVtcILKBzQo=','86cf5e15df0ba874e1fec66d717fd45215b7f00003ddbc1b01447eddebd13a45','+254 7** *** 003','female','ward-a','not_found','en',2,'2026-10-29 22:35:35.872838');
INSERT INTO "farmer" VALUES('d2dbe41a49af4edb8fbd37926140de6d',1,'D-0004','Mwangi Njoroge (fictional)','zs9ApyVxSVr7Z2DVp4wdF8wVFNXgdMdxQ+8VGTXWiBaRjXba','e78119b7025437339e40c3ae1d0d114cf039481626c8f2894989e8850709aa9a','*****004','9XaxGpNupiXhc8YjVhkIFJ0S9rrmKF346ncFzrJhgKjyrAlrHYnVkcA=','9360d7c64809eed301732daa375b3fd69bd53059323ebd56373ea9c4c21a168c','+254 7** *** 004','male','ward-a','not_found','sw',2,'2026-10-29 22:35:35.886952');
INSERT INTO "farmer" VALUES('85296c3b3d25486f982860996cf0383c',1,'D-0005','Chebet Rotich (fictional)','49ArFAbPHVc2vEwdLE06m5fCwcnwplHyYz9RFd4RwYPbFVwq','c3141430c3176a2551aae391eae7afa71dfad7be3ebe0228f23fa27490026803','*****005','EE9p5zqyYL1DQwupo89a2hvsaBGd4B750E5K6cgrLryBAxvuz5AwYKw=','a214eefe4738ac502af89bb4ae3f7baec8fe3ea65248be32a37a7b4716c3ca0d','+254 7** *** 005','female','ward-a','not_found','sw',2,'2026-10-29 22:35:35.900949');
INSERT INTO "farmer" VALUES('a568f3f6b128464692c229804a6ffdcd',1,'D-0006','Otieno Ouma (fictional)','OSg/c39hv3nKsE3OZSy8Qgfk2fkKEzfnEjdSZ3RapZoyPPoO','3a1ceee102c760d40180e54e80b08466bebd26c06b1aa969ae831a78bd5153a6','*****006','fBXUxKSLXww5gTZHYnL6r1Hsh8yIQxg0F6dDzdRz0Z6Vq/8jp/HsqAQ=','2721e51d24cef20f3674d611c34fa08cbd90ee97d9466c17cbc12fba24de94c4','+254 7** *** 006','male','ward-a','not_found','en',2,'2026-10-29 22:35:35.915950');
INSERT INTO "farmer" VALUES('585fa9aa8d7e40cab55dbc201bb1897c',2,'M-0001','Nafula Wekesa (fictional)','nV6gUdza1AHsFoEo9EOHye3qcw7PCELui+nRJMn6QUi2rgaD','683c79f75c75d1cc5d52ec2d13cf0065c03a7e228be93be67f2829334edd196f','*****011','YccwXyS2gkzkPBFATSk1hYT+oMhsablIAYgckGNmNoOYax50Qy60jKg=','bacc2d9c40a0bd062a7e81d544895d4c354aafe27256d12eac24d4a9d9849420','+254 7** *** 011','female','ward-a','not_found','sw',2,'2026-10-29 22:35:36.436974');
INSERT INTO "farmer" VALUES('19d17f7f5cbe47758370752962744e4c',2,'M-0002','Kamau Gitau (fictional)','RbZ4TdhWoq4kIlKfTpa12kdEMKiBseltmBnv/7iKXz6Q/TUX','27a70651dc7dbb93680935e2e97ffc5027e2d07389256a27874f9312d2c84f70','*****012','yBiNAkoOTynCQZM7WMh1UUh+KyRIDvFV3lxXzdjMoy/LWt3vbqShfNY=','a8193bfdf09b8205d8e48b5748184aed9960933ab0536d73fade008ef4873511','+254 7** *** 012','male','ward-a','not_found','en',2,'2026-10-29 22:35:36.445127');
CREATE TABLE insurer (
	id INTEGER NOT NULL, 
	code VARCHAR(16) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	is_demo BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
);
INSERT INTO "insurer" VALUES(1,'DEMOUW','Demo Insurer (fictional)',1,'2026-10-29 22:35:35.613925');
CREATE TABLE kiamis_record (
	id INTEGER NOT NULL, 
	national_id_hash VARCHAR(64) NOT NULL, 
	registered_acreage FLOAT, 
	certified_seed_purchased BOOLEAN NOT NULL, 
	subsidy_eligible BOOLEAN, 
	imported_at DATETIME NOT NULL, 
	source_sha256 VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (national_id_hash)
);
CREATE TABLE missed_payout_report (
	id INTEGER NOT NULL, 
	ref VARCHAR(12) NOT NULL, 
	farmer_id VARCHAR(32) NOT NULL, 
	policy_id VARCHAR(32), 
	ward_id VARCHAR(40) NOT NULL, 
	season VARCHAR(4) NOT NULL, 
	year INTEGER NOT NULL, 
	category VARCHAR(24) NOT NULL, 
	channel VARCHAR(10) NOT NULL, 
	note VARCHAR(500), 
	index_snapshot JSON NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	outcome VARCHAR(30), 
	review_note VARCHAR(500), 
	reviewed_by VARCHAR(60), 
	reviewed_at DATETIME, 
	reported_by VARCHAR(60) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (ref), 
	FOREIGN KEY(farmer_id) REFERENCES farmer (id), 
	FOREIGN KEY(policy_id) REFERENCES policy (id)
);
CREATE TABLE mpesa_request (
	id INTEGER NOT NULL, 
	policy_id VARCHAR(32) NOT NULL, 
	amount_kes INTEGER NOT NULL, 
	phone_masked VARCHAR(24) NOT NULL, 
	merchant_request_id VARCHAR(60) NOT NULL, 
	checkout_request_id VARCHAR(60) NOT NULL, 
	environment VARCHAR(12) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	result_code INTEGER, 
	result_desc VARCHAR(200), 
	receipt VARCHAR(30), 
	requested_by VARCHAR(60) NOT NULL, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES policy (id), 
	UNIQUE (checkout_request_id)
);
INSERT INTO "mpesa_request" VALUES(1,'38034213c61a4f8e853956b81ad0d092',1599,'+254 7** *** 002','SIM-b3adda898412','ws_CO_SIM_b3adda898412','simulated','paid',0,'The service request is processed successfully.','SIM354CE4B9','demo-manager','2026-10-29 22:35:35.921141','2026-10-30 01:35:35.921141');
INSERT INTO "mpesa_request" VALUES(2,'ca3c309229b24a149f9c67680d57d750',880,'+254 7** *** 003','SIM-17c2d37f8947','ws_CO_SIM_17c2d37f8947','simulated','pending',NULL,NULL,NULL,'demo-manager','2026-10-29 22:35:35.935956',NULL);
CREATE TABLE officer (
	id INTEGER NOT NULL, 
	sacco_id INTEGER, 
	insurer_id INTEGER, 
	username VARCHAR(60) NOT NULL, 
	display_name VARCHAR(120) NOT NULL, 
	password_hash VARCHAR(200) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(sacco_id) REFERENCES sacco (id), 
	FOREIGN KEY(insurer_id) REFERENCES insurer (id), 
	UNIQUE (username)
);
INSERT INTO "officer" VALUES(1,NULL,1,'demo-underwriter','Demo Underwriter','scrypt$16384$8$1$IDVnpPNpiFq1DtKSX1Q2wQ==$W9T3ZqOF5d5EfWboDE0IP2qkWUL2SI0TChUCLnCKgCI=','underwriter',1,'2026-10-29 22:35:35.817886');
INSERT INTO "officer" VALUES(2,1,NULL,'demo-manager','Demo Manager','scrypt$16384$8$1$YtObtXQONZS/enQ2K80yVA==$1Gr5VNkU0rK+L8sr8L2F82XNlsw1yx5lvtWRRzJXniE=','manager',1,'2026-10-29 22:35:35.817886');
INSERT INTO "officer" VALUES(3,1,NULL,'demo-officer','Grace (demo officer)','scrypt$16384$8$1$NzKWiEeUw+8tz+VEklrezw==$5tsJAyoqZHuR79TwboKIgCFb+QCQkzHybod2BAFRsDI=','officer',1,'2026-10-29 22:35:35.817886');
CREATE TABLE payment (
	id INTEGER NOT NULL, 
	policy_id VARCHAR(32) NOT NULL, 
	amount_kes FLOAT NOT NULL, 
	method VARCHAR(20) NOT NULL, 
	reference VARCHAR(40) NOT NULL, 
	received_at DATETIME NOT NULL, 
	within_window BOOLEAN NOT NULL, 
	recorded_by VARCHAR(60) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(policy_id) REFERENCES policy (id), 
	UNIQUE (reference)
);
INSERT INTO "payment" VALUES(1,'8b7fe3c205944dda97e2c83aa866a340',1753.0,'sacco_deduction','DEMO-DED-0001','2026-10-30 01:35:35.921141',1,'demo-manager','2026-10-29 22:35:35.921141');
INSERT INTO "payment" VALUES(2,'38034213c61a4f8e853956b81ad0d092',1599.0,'mpesa','SIM354CE4B9','2026-10-30 01:35:35.000000',1,'mpesa','2026-10-29 22:35:35.921141');
INSERT INTO "payment" VALUES(3,'d8a11ccf7812418d809dfe1b8bcf400d',1000.0,'sacco_deduction','DEMO-DED-0004','2026-10-30 01:35:35.936957',1,'demo-manager','2026-10-29 22:35:35.936957');
INSERT INTO "payment" VALUES(4,'08353011bfc84f8eb328ebc7eedc5ac4',1753.0,'sacco_deduction','DEMO-2008-0','2008-01-20 10:00:00.000000',1,'demo-manager','2026-10-29 22:35:35.971613');
INSERT INTO "payment" VALUES(5,'5eb2801dcd404067a835489b9e1640a7',3199.0,'sacco_deduction','DEMO-2008-1','2008-01-20 10:00:00.000000',1,'demo-manager','2026-10-29 22:35:35.971613');
INSERT INTO "payment" VALUES(6,'dbda1916ed4749479ac80032900bf864',880.0,'sacco_deduction','DEMO-2008-2','2008-01-20 10:00:00.000000',1,'demo-manager','2026-10-29 22:35:35.971613');
CREATE TABLE payout (
	id INTEGER NOT NULL, 
	policy_id VARCHAR(32) NOT NULL, 
	kind VARCHAR(24) NOT NULL, 
	share FLOAT, 
	amount_kes FLOAT NOT NULL, 
	ward_status_id INTEGER NOT NULL, 
	index_version VARCHAR(20) NOT NULL, 
	confirmed_on DATE NOT NULL, 
	due_by DATE NOT NULL, 
	method VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	approved_by VARCHAR(60), 
	approved_at DATETIME, 
	hold_reason VARCHAR(300), 
	voucher_code VARCHAR(16), 
	reference VARCHAR(40), 
	paid_at DATETIME, 
	paid_by VARCHAR(60), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (policy_id, kind), 
	FOREIGN KEY(policy_id) REFERENCES policy (id), 
	FOREIGN KEY(ward_status_id) REFERENCES ward_status (id), 
	UNIQUE (voucher_code)
);
INSERT INTO "payout" VALUES(1,'08353011bfc84f8eb328ebc7eedc5ac4','wrsi',0.414,8280.0,3,'B-1.2.0','2008-09-01','2008-09-11','mpesa','paid','demo-underwriter','2026-10-29 22:35:36.429294',NULL,NULL,'SIMB2C1AC380C3','2026-10-29 22:35:36.429294','demo-manager','2026-10-29 22:35:36.219218');
INSERT INTO "payout" VALUES(2,'5eb2801dcd404067a835489b9e1640a7','wrsi',0.414,14490.0,3,'B-1.2.0','2008-09-01','2008-09-11','sacco_loan','approved','demo-underwriter','2026-10-29 22:35:36.429294',NULL,NULL,NULL,NULL,NULL,'2026-10-29 22:35:36.424411');
INSERT INTO "payout" VALUES(3,'dbda1916ed4749479ac80032900bf864','wrsi',0.414,3105.0,3,'B-1.2.0','2008-09-01','2008-09-11','mpesa','calculated',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2026-10-29 22:35:36.425443');
CREATE TABLE plot (
	id VARCHAR(32) NOT NULL, 
	farmer_id VARCHAR(32) NOT NULL, 
	ward_id VARCHAR(40) NOT NULL, 
	crop VARCHAR(30) NOT NULL, 
	acreage FLOAT NOT NULL, 
	lat FLOAT, 
	lon FLOAT, 
	polygon_geojson TEXT, 
	source VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(farmer_id) REFERENCES farmer (id)
);
INSERT INTO "plot" VALUES('91bbb4d2cdaf4c18af47b7522009842e','a78772c762ee43d89d48124867dc972f','ward-a','maize',2.0,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.842699');
INSERT INTO "plot" VALUES('675e0a77949245f8b74797af1880e897','60c86eab900044269448bfc32fc33c98','ward-a','maize',3.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.863704');
INSERT INTO "plot" VALUES('a61c73589148468d8012a6d27817f15c','1397f4913ee9466aba5bce95da0189f6','ward-a','maize',1.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.883948');
INSERT INTO "plot" VALUES('dbf86f75342c4d9682b3b59864621c09','d2dbe41a49af4edb8fbd37926140de6d','ward-a','maize',4.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.894954');
INSERT INTO "plot" VALUES('0d5cae0e42f140c882299359ee4777be','85296c3b3d25486f982860996cf0383c','ward-a','maize',0.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.909948');
INSERT INTO "plot" VALUES('8ccbf1e872594cc1ad21d4b95f45e0b9','a568f3f6b128464692c229804a6ffdcd','ward-a','maize',5.0,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.920175');
INSERT INTO "plot" VALUES('0d5fe3ad4a03482fa0683038733583ec','a78772c762ee43d89d48124867dc972f','ward-a','maize',2.0,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.948958');
INSERT INTO "plot" VALUES('f018a6304b81457c801a4f4f12460b0a','60c86eab900044269448bfc32fc33c98','ward-a','maize',3.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.955069');
INSERT INTO "plot" VALUES('949b1d43bc0a4bdcbb06262dd5e4ef76','1397f4913ee9466aba5bce95da0189f6','ward-a','maize',1.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.955069');
INSERT INTO "plot" VALUES('f75263685dd1426285a2f97d5c63767d','d2dbe41a49af4edb8fbd37926140de6d','ward-a','maize',4.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:35.969275');
INSERT INTO "plot" VALUES('ae6e67361c874dc8821cc30d2546565f','585fa9aa8d7e40cab55dbc201bb1897c','ward-a','maize',3.0,NULL,NULL,NULL,'csv','2026-10-29 22:35:36.439973');
INSERT INTO "plot" VALUES('56d1d29489ab44609ea96327baa20e4a','19d17f7f5cbe47758370752962744e4c','ward-a','maize',2.5,NULL,NULL,NULL,'csv','2026-10-29 22:35:36.448169');
CREATE TABLE policy (
	id VARCHAR(32) NOT NULL, 
	policy_no VARCHAR(40) NOT NULL, 
	insurer_policy_number VARCHAR(60), 
	pay_ref VARCHAR(12) NOT NULL, 
	farmer_id VARCHAR(32) NOT NULL, 
	plot_id VARCHAR(32) NOT NULL, 
	sacco_id INTEGER NOT NULL, 
	insurer_id INTEGER, 
	ward_id VARCHAR(40) NOT NULL, 
	season VARCHAR(4) NOT NULL, 
	year INTEGER NOT NULL, 
	layers VARCHAR(8) NOT NULL, 
	acres FLOAT NOT NULL, 
	sum_insured_per_acre FLOAT, 
	gross_kes FLOAT NOT NULL, 
	government_share_kes FLOAT NOT NULL, 
	farmer_share_kes FLOAT NOT NULL, 
	resilience_points FLOAT NOT NULL, 
	discount_kes FLOAT NOT NULL, 
	discount_funder VARCHAR(20) NOT NULL, 
	farmer_pays_kes FLOAT NOT NULL, 
	amount_due_kes INTEGER NOT NULL, 
	paid_kes FLOAT NOT NULL, 
	refund_due_kes FLOAT NOT NULL, 
	sales_closes_on DATE NOT NULL, 
	cover_active_from DATETIME, 
	subsidy_status VARCHAR(20) NOT NULL, 
	payment_route VARCHAR(20) NOT NULL, 
	payment_status VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	loan_linked BOOLEAN NOT NULL, 
	loan_ref VARCHAR(40), 
	quote_id VARCHAR(40) NOT NULL, 
	quote_snapshot JSON NOT NULL, 
	created_by INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (plot_id, season, year), 
	UNIQUE (policy_no), 
	UNIQUE (pay_ref), 
	FOREIGN KEY(farmer_id) REFERENCES farmer (id), 
	FOREIGN KEY(plot_id) REFERENCES plot (id), 
	FOREIGN KEY(sacco_id) REFERENCES sacco (id), 
	FOREIGN KEY(insurer_id) REFERENCES insurer (id), 
	FOREIGN KEY(created_by) REFERENCES officer (id)
);
INSERT INTO "policy" VALUES('8b7fe3c205944dda97e2c83aa866a340','AGS-DEMO-LR27-00001',NULL,'AGPWN59T6X','a78772c762ee43d89d48124867dc972f','91bbb4d2cdaf4c18af47b7522009842e',1,1,'ward-a','LR',2027,'B',2.0,10000.0,3768.1,1884.05,1884.05,7.0,131.88,'platform',1752.17,1753,1753.0,0.0,'2027-02-14','2026-10-30 01:35:35.921141','not yet received','sacco_deduction','paid','active',0,NULL,'Q-20261029-e2e30043','{"quote_id": "Q-20261029-e2e30043", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 2.0, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 20000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 3768.1, "government_share_kes": 1884.05, "farmer_share_kes": 1884.05}], "gross_premium_kes": 3768.1, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 1884.05, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 1884.05, "resilience": {"points": 7.0, "items_counted": [{"id": "certified_seed_verified", "label": "Certified seed bought last season", "points": 5.0, "verified_by": "agro-dealer receipt or KIAMIS"}, {"id": "sacco_good_standing", "label": "SACCO member in good standing (savings or loan current)", "points": 2.0, "verified_by": "SACCO records"}], "discount_rate": 0.07, "discount_cap": 0.15, "capped": false, "discount_kes": 131.88, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 3768.1, "government_kes": 1884.05, "farmer_kes": 1752.17, "discount_funder": "platform", "discount_funder_kes": 131.88, "platform_fee_kes": 226.09, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 1752.17, "farmer_pays_rounded_kes": 1752, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.847704');
INSERT INTO "policy" VALUES('38034213c61a4f8e853956b81ad0d092','AGS-DEMO-LR27-00002',NULL,'AGERGLA34C','60c86eab900044269448bfc32fc33c98','675e0a77949245f8b74797af1880e897',1,1,'ward-a','LR',2027,'B',3.5,10000.0,6594.18,3297.09,3297.09,3.0,98.91,'platform',3198.18,3199,1599.0,0.0,'2027-02-14',NULL,'not yet received','mpesa','part_paid','pending_payment',1,'LN-0042','Q-20261029-e6eb915b','{"quote_id": "Q-20261029-e6eb915b", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 3.5, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 35000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 6594.18, "government_share_kes": 3297.09, "farmer_share_kes": 3297.09}], "gross_premium_kes": 6594.18, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 3297.09, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 3297.09, "resilience": {"points": 3.0, "items_counted": [{"id": "practices_verified", "label": "Good practices verified (timely planting, mulching, conservation tillage)", "points": 3.0, "verified_by": "champion farmer or extension officer"}], "discount_rate": 0.03, "discount_cap": 0.15, "capped": false, "discount_kes": 98.91, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 6594.18, "government_kes": 3297.09, "farmer_kes": 3198.18, "discount_funder": "platform", "discount_funder_kes": 98.91, "platform_fee_kes": 395.65, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 3198.18, "farmer_pays_rounded_kes": 3198, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.864706');
INSERT INTO "policy" VALUES('ca3c309229b24a149f9c67680d57d750','AGS-DEMO-LR27-00003',NULL,'AG2EAMP234','1397f4913ee9466aba5bce95da0189f6','a61c73589148468d8012a6d27817f15c',1,1,'ward-a','LR',2027,'B',1.5,5000.0,1759.76,879.88,879.88,0.0,0.0,'platform',879.88,880,0.0,0.0,'2027-02-14',NULL,'not yet received','mpesa','pending','pending_payment',0,NULL,'Q-20261029-7412656b','{"quote_id": "Q-20261029-7412656b", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 1.5, "sum_insured_kes_per_acre": 5000.0, "total_sum_insured_kes": 7500.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1173.17, "cover": "up to KES 5,000/acre", "gross_kes": 1759.76, "government_share_kes": 879.88, "farmer_share_kes": 879.88}], "gross_premium_kes": 1759.76, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 879.88, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 879.88, "resilience": {"points": 0, "items_counted": [], "discount_rate": 0.0, "discount_cap": 0.15, "capped": false, "discount_kes": 0.0, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 1759.76, "government_kes": 879.88, "farmer_kes": 879.88, "discount_funder": "platform", "discount_funder_kes": 0.0, "platform_fee_kes": 105.59, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 879.88, "farmer_pays_rounded_kes": 880, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.884949');
INSERT INTO "policy" VALUES('d8a11ccf7812418d809dfe1b8bcf400d','AGS-DEMO-LR27-00004',NULL,'AGZ6X2F86Q','d2dbe41a49af4edb8fbd37926140de6d','dbf86f75342c4d9682b3b59864621c09',1,1,'ward-a','LR',2027,'B',4.5,10000.0,8478.23,4239.12,4239.11,4.0,169.56,'platform',4069.55,4070,1000.0,0.0,'2027-02-14',NULL,'not yet received','sacco_deduction','part_paid','pending_payment',1,'LN-0107','Q-20261029-4dbf9759','{"quote_id": "Q-20261029-4dbf9759", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 4.5, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 45000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 8478.23, "government_share_kes": 4239.12, "farmer_share_kes": 4239.11}], "gross_premium_kes": 8478.23, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 4239.12, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 4239.11, "resilience": {"points": 4.0, "items_counted": [{"id": "irrigation_partial", "label": "Partial or supplementary irrigation", "points": 2.0, "verified_by": "officer visit"}, {"id": "sacco_good_standing", "label": "SACCO member in good standing (savings or loan current)", "points": 2.0, "verified_by": "SACCO records"}], "discount_rate": 0.04, "discount_cap": 0.15, "capped": false, "discount_kes": 169.56, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 8478.23, "government_kes": 4239.12, "farmer_kes": 4069.55, "discount_funder": "platform", "discount_funder_kes": 169.56, "platform_fee_kes": 508.69, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 4069.55, "farmer_pays_rounded_kes": 4070, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.896949');
INSERT INTO "policy" VALUES('c171f6893b4e41ccbedcf016ec8237f7','AGS-DEMO-LR27-00005',NULL,'AGC8KN6XYR','85296c3b3d25486f982860996cf0383c','0d5cae0e42f140c882299359ee4777be',1,1,'ward-a','LR',2027,'B',0.5,10000.0,942.03,471.02,471.01,0.0,0.0,'platform',471.01,472,0.0,0.0,'2027-02-14',NULL,'not yet received','mpesa','pending','pending_payment',0,NULL,'Q-20261029-6e95f9be','{"quote_id": "Q-20261029-6e95f9be", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 0.5, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 5000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 942.03, "government_share_kes": 471.02, "farmer_share_kes": 471.01}], "gross_premium_kes": 942.03, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 471.02, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 471.01, "resilience": {"points": 0, "items_counted": [], "discount_rate": 0.0, "discount_cap": 0.15, "capped": false, "discount_kes": 0.0, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 942.03, "government_kes": 471.02, "farmer_kes": 471.01, "discount_funder": "platform", "discount_funder_kes": 0.0, "platform_fee_kes": 56.52, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 471.01, "farmer_pays_rounded_kes": 471, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.911953');
INSERT INTO "policy" VALUES('7dfc27a0a10a4a67a7819e8e33198d79','AGS-DEMO-LR27-00006',NULL,'AGKYUCTY38','a568f3f6b128464692c229804a6ffdcd','8ccbf1e872594cc1ad21d4b95f45e0b9',1,1,'ward-a','LR',2027,'B',5.0,10000.0,9420.25,4710.13,4710.12,5.0,235.51,'platform',4474.61,4475,0.0,0.0,'2027-02-14',NULL,'not yet received','sacco_deduction','pending','pending_payment',0,NULL,'Q-20261029-800d472c','{"quote_id": "Q-20261029-800d472c", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 5.0, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 50000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 9420.25, "government_share_kes": 4710.13, "farmer_share_kes": 4710.12}], "gross_premium_kes": 9420.25, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 4710.13, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 4710.12, "resilience": {"points": 5.0, "items_counted": [{"id": "certified_seed_verified", "label": "Certified seed bought last season", "points": 5.0, "verified_by": "agro-dealer receipt or KIAMIS"}], "discount_rate": 0.05, "discount_cap": 0.15, "capped": false, "discount_kes": 235.51, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 9420.25, "government_kes": 4710.13, "farmer_kes": 4474.61, "discount_funder": "platform", "discount_funder_kes": 235.51, "platform_fee_kes": 565.22, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 4474.61, "farmer_pays_rounded_kes": 4475, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.921141');
INSERT INTO "policy" VALUES('08353011bfc84f8eb328ebc7eedc5ac4','AGS-DEMO-LR08-00007',NULL,'AGKC6VRLUF','a78772c762ee43d89d48124867dc972f','0d5fe3ad4a03482fa0683038733583ec',1,1,'ward-a','LR',2008,'B',2.0,10000.0,3768.1,1884.05,1884.05,7.0,131.88,'platform',1752.17,1753,1753.0,0.0,'2008-02-14','2008-01-20 10:00:00.000000','not yet received','sacco_deduction','paid','active',0,NULL,'Q-20261029-8f267586','{"quote_id": "Q-20261029-8f267586", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 2.0, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 20000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 3768.1, "government_share_kes": 1884.05, "farmer_share_kes": 1884.05}], "gross_premium_kes": 3768.1, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 1884.05, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 1884.05, "resilience": {"points": 7.0, "items_counted": [{"id": "certified_seed_verified", "label": "Certified seed bought last season", "points": 5.0, "verified_by": "agro-dealer receipt or KIAMIS"}, {"id": "sacco_good_standing", "label": "SACCO member in good standing (savings or loan current)", "points": 2.0, "verified_by": "SACCO records"}], "discount_rate": 0.07, "discount_cap": 0.15, "capped": false, "discount_kes": 131.88, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 3768.1, "government_kes": 1884.05, "farmer_kes": 1752.17, "discount_funder": "platform", "discount_funder_kes": 131.88, "platform_fee_kes": 226.09, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 1752.17, "farmer_pays_rounded_kes": 1752, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.949920');
INSERT INTO "policy" VALUES('5eb2801dcd404067a835489b9e1640a7','AGS-DEMO-LR08-00008',NULL,'AG4JZUU7L5','60c86eab900044269448bfc32fc33c98','f018a6304b81457c801a4f4f12460b0a',1,1,'ward-a','LR',2008,'B',3.5,10000.0,6594.18,3297.09,3297.09,3.0,98.91,'platform',3198.18,3199,3199.0,0.0,'2008-02-14','2008-01-20 10:00:00.000000','not yet received','mpesa','paid','active',1,'LN-0042','Q-20261029-7c267b01','{"quote_id": "Q-20261029-7c267b01", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 3.5, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 35000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 6594.18, "government_share_kes": 3297.09, "farmer_share_kes": 3297.09}], "gross_premium_kes": 6594.18, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 3297.09, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 3297.09, "resilience": {"points": 3.0, "items_counted": [{"id": "practices_verified", "label": "Good practices verified (timely planting, mulching, conservation tillage)", "points": 3.0, "verified_by": "champion farmer or extension officer"}], "discount_rate": 0.03, "discount_cap": 0.15, "capped": false, "discount_kes": 98.91, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 6594.18, "government_kes": 3297.09, "farmer_kes": 3198.18, "discount_funder": "platform", "discount_funder_kes": 98.91, "platform_fee_kes": 395.65, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 3198.18, "farmer_pays_rounded_kes": 3198, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.955069');
INSERT INTO "policy" VALUES('dbda1916ed4749479ac80032900bf864','AGS-DEMO-LR08-00009',NULL,'AGQC2Z4GYR','1397f4913ee9466aba5bce95da0189f6','949b1d43bc0a4bdcbb06262dd5e4ef76',1,1,'ward-a','LR',2008,'B',1.5,5000.0,1759.76,879.88,879.88,0.0,0.0,'platform',879.88,880,880.0,0.0,'2008-02-14','2008-01-20 10:00:00.000000','not yet received','mpesa','paid','active',0,NULL,'Q-20261029-6f7b9590','{"quote_id": "Q-20261029-6f7b9590", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 1.5, "sum_insured_kes_per_acre": 5000.0, "total_sum_insured_kes": 7500.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1173.17, "cover": "up to KES 5,000/acre", "gross_kes": 1759.76, "government_share_kes": 879.88, "farmer_share_kes": 879.88}], "gross_premium_kes": 1759.76, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 879.88, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 879.88, "resilience": {"points": 0, "items_counted": [], "discount_rate": 0.0, "discount_cap": 0.15, "capped": false, "discount_kes": 0.0, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 1759.76, "government_kes": 879.88, "farmer_kes": 879.88, "discount_funder": "platform", "discount_funder_kes": 0.0, "platform_fee_kes": 105.59, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 879.88, "farmer_pays_rounded_kes": 880, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.955069');
INSERT INTO "policy" VALUES('d6aff0dab313420e8a3157b56aa3bf06','AGS-DEMO-LR08-00010',NULL,'AG8KLMKRNV','d2dbe41a49af4edb8fbd37926140de6d','f75263685dd1426285a2f97d5c63767d',1,1,'ward-a','LR',2008,'B',4.5,10000.0,8478.23,4239.12,4239.11,4.0,169.56,'platform',4069.55,4070,0.0,0.0,'2008-02-14',NULL,'not yet received','sacco_deduction','pending','lapsed_unpaid',1,'LN-0107','Q-20261029-1f3b41e6','{"quote_id": "Q-20261029-1f3b41e6", "created_at": "2026-10-29T22:35:35+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 4.5, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 45000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 8478.23, "government_share_kes": 4239.12, "farmer_share_kes": 4239.11}], "gross_premium_kes": 8478.23, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 4239.12, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 4239.11, "resilience": {"points": 4.0, "items_counted": [{"id": "irrigation_partial", "label": "Partial or supplementary irrigation", "points": 2.0, "verified_by": "officer visit"}, {"id": "sacco_good_standing", "label": "SACCO member in good standing (savings or loan current)", "points": 2.0, "verified_by": "SACCO records"}], "discount_rate": 0.04, "discount_cap": 0.15, "capped": false, "discount_kes": 169.56, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 8478.23, "government_kes": 4239.12, "farmer_kes": 4069.55, "discount_funder": "platform", "discount_funder_kes": 169.56, "platform_fee_kes": 508.69, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 4069.55, "farmer_pays_rounded_kes": 4070, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:35.971239');
INSERT INTO "policy" VALUES('4287ffcd4767475b8ac915149e90ed81','AGS-DEMO2-LR27-00001',NULL,'AGNJDRUMKJ','585fa9aa8d7e40cab55dbc201bb1897c','ae6e67361c874dc8821cc30d2546565f',2,1,'ward-a','LR',2027,'B',3.0,10000.0,5652.15,2826.08,2826.07,5.0,141.3,'platform',2684.77,2685,0.0,0.0,'2027-02-14',NULL,'not yet received','mpesa','pending','pending_payment',0,NULL,'Q-20261029-cdee2edf','{"quote_id": "Q-20261029-cdee2edf", "created_at": "2026-10-29T22:35:36+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 3.0, "sum_insured_kes_per_acre": 10000.0, "total_sum_insured_kes": 30000.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 1884.05, "cover": "up to KES 10,000/acre", "gross_kes": 5652.15, "government_share_kes": 2826.08, "farmer_share_kes": 2826.07}], "gross_premium_kes": 5652.15, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 2826.08, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 2826.07, "resilience": {"points": 5.0, "items_counted": [{"id": "certified_seed_verified", "label": "Certified seed bought last season", "points": 5.0, "verified_by": "agro-dealer receipt or KIAMIS"}], "discount_rate": 0.05, "discount_cap": 0.15, "capped": false, "discount_kes": 141.3, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 5652.15, "government_kes": 2826.08, "farmer_kes": 2684.77, "discount_funder": "platform", "discount_funder_kes": 141.3, "platform_fee_kes": 339.13, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 2684.77, "farmer_pays_rounded_kes": 2685, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:36.441974');
INSERT INTO "policy" VALUES('60121f393b2a4e108e57beb18c70d74c','AGS-DEMO2-LR27-00002',NULL,'AGKF6LCK9T','19d17f7f5cbe47758370752962744e4c','56d1d29489ab44609ea96327baa20e4a',2,1,'ward-a','LR',2027,'B',2.5,15000.0,6548.4,3274.2,3274.2,0.0,0.0,'platform',3274.2,3275,0.0,0.0,'2027-02-14',NULL,'not yet received','sacco_deduction','pending','pending_payment',0,NULL,'Q-20261029-e7425e7c','{"quote_id": "Q-20261029-e7425e7c", "created_at": "2026-10-29T22:35:36+00:00", "ward": {"id": "ward-a", "name": "Illustrative Ward A (lowland, near Rongai)"}, "season": "LR", "acres": 2.5, "sum_insured_kes_per_acre": 15000.0, "total_sum_insured_kes": 37500.0, "layers": [{"layer": "B", "name": "In-season rainfall index (WRSI) with replanting voucher", "gross_per_acre_kes": 2619.36, "cover": "up to KES 15,000/acre", "gross_kes": 6548.4, "government_share_kes": 3274.2, "farmer_share_kes": 3274.2}], "gross_premium_kes": 6548.4, "subsidy": {"programme": "KAIP", "eligible": true, "eligibility": "0.5 to 20 acres", "government_share_rate": 0.5, "government_share_kes": 3274.2, "status": "not yet received", "note": "The government share is recorded as a receivable until KAIP pays it."}, "farmer_share_before_discount_kes": 3274.2, "resilience": {"points": 0, "items_counted": [], "discount_rate": 0.0, "discount_cap": 0.15, "capped": false, "discount_kes": 0.0, "applies_to": "farmer share only", "funder": "platform", "note": "Paid by the funder; the insurer still receives the full gross premium. The discount does not reduce the parametric risk."}, "premium_flows": {"insurer_receives_kes": 6548.4, "government_kes": 3274.2, "farmer_kes": 3274.2, "discount_funder": "platform", "discount_funder_kes": 0.0, "platform_fee_kes": 392.9, "discount_exceeds_platform_fee": false}, "farmer_pays_kes": 3274.2, "farmer_pays_rounded_kes": 3274, "payment": "M-Pesa or SACCO deduction (milestone 6)", "basis": {"index_versions": {"layer_b": "B-1.2.0"}, "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "rate_book_built_at": "2026-10-29T22:35:35+00:00", "inputs": ["ILLUSTRATIVE", "PENDING", "REAL", "SYNTHETIC"], "illustrative": true, "note": "Illustrative pricing: not a filed product and not for sale."}}',2,'2026-10-29 22:35:36.449214');
CREATE TABLE premium_remittance (
	id INTEGER NOT NULL, 
	ref VARCHAR(12) NOT NULL, 
	sacco_id INTEGER NOT NULL, 
	insurer_id INTEGER NOT NULL, 
	amount_kes FLOAT NOT NULL, 
	remitted_on DATE NOT NULL, 
	method VARCHAR(16) NOT NULL, 
	reference VARCHAR(40) NOT NULL, 
	period VARCHAR(20), 
	note VARCHAR(300), 
	status VARCHAR(12) NOT NULL, 
	recorded_by VARCHAR(60) NOT NULL, 
	reviewed_by VARCHAR(60), 
	reviewed_at DATETIME, 
	review_note VARCHAR(300), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (ref), 
	FOREIGN KEY(sacco_id) REFERENCES sacco (id), 
	FOREIGN KEY(insurer_id) REFERENCES insurer (id)
);
INSERT INTO "premium_remittance" VALUES(1,'RM-5C38FC',1,1,5000.0,'2026-10-30','bank_transfer','DEMO-BANK-0001','2027-LR','fictional demo remittance','recorded','demo-manager',NULL,NULL,NULL,'2026-10-29 22:35:36.453214');
CREATE TABLE public_enquiry (
	id INTEGER NOT NULL, 
	ref VARCHAR(12) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	name_enc TEXT NOT NULL, 
	email_enc TEXT NOT NULL, 
	email_masked VARCHAR(80) NOT NULL, 
	phone_enc TEXT, 
	phone_masked VARCHAR(24), 
	organisation VARCHAR(120), 
	org_type VARCHAR(20) NOT NULL, 
	county VARCHAR(40), 
	message VARCHAR(1000), 
	consent_text VARCHAR(300) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (ref)
);
CREATE TABLE sacco (
	id INTEGER NOT NULL, 
	code VARCHAR(16) NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	county VARCHAR(60) NOT NULL, 
	is_demo BOOLEAN NOT NULL, 
	insurer_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	FOREIGN KEY(insurer_id) REFERENCES insurer (id)
);
INSERT INTO "sacco" VALUES(1,'DEMO','Demo SACCO (fictional)','Nakuru',1,1,'2026-10-29 22:35:35.616277');
INSERT INTO "sacco" VALUES(2,'DEMO2','Demo Molo SACCO (fictional)','Nakuru',1,1,'2026-10-29 22:35:36.434972');
CREATE TABLE sms_message (
	id INTEGER NOT NULL, 
	farmer_id VARCHAR(32) NOT NULL, 
	policy_id VARCHAR(32), 
	template VARCHAR(30) NOT NULL, 
	language VARCHAR(2) NOT NULL, 
	body VARCHAR(320) NOT NULL, 
	dedupe_key VARCHAR(80), 
	status VARCHAR(12) NOT NULL, 
	provider VARCHAR(20), 
	provider_message_id VARCHAR(80), 
	error VARCHAR(200), 
	created_at DATETIME NOT NULL, 
	sent_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(farmer_id) REFERENCES farmer (id), 
	FOREIGN KEY(policy_id) REFERENCES policy (id), 
	UNIQUE (dedupe_key)
);
INSERT INTO "sms_message" VALUES(1,'a78772c762ee43d89d48124867dc972f','8b7fe3c205944dda97e2c83aa866a340','enrolled','sw','AgroShield: Wanjiku, umesajiliwa bima ya mahindi masika 2027, AGS-DEMO-LR27-00001. Lipa KES 1,753 kufikia 14/02/2027 (M-Pesa/SACCO). Piga *384*000#.','enrolled:8b7fe3c205944dda97e2c83aa866a340','logged','log',NULL,NULL,'2026-10-29 22:35:35.858705','2026-10-29 22:35:36.478474');
INSERT INTO "sms_message" VALUES(2,'60c86eab900044269448bfc32fc33c98','38034213c61a4f8e853956b81ad0d092','enrolled','en','AgroShield: Kiprono, enrolled for long rains 2027 maize cover AGS-DEMO-LR27-00002. Pay KES 3,199 by 14/02/2027 (M-Pesa or SACCO). Dial *384*000#.','enrolled:38034213c61a4f8e853956b81ad0d092','logged','log',NULL,NULL,'2026-10-29 22:35:35.872838','2026-10-29 22:35:36.480446');
INSERT INTO "sms_message" VALUES(3,'d2dbe41a49af4edb8fbd37926140de6d','d8a11ccf7812418d809dfe1b8bcf400d','enrolled','sw','AgroShield: Mwangi, umesajiliwa bima ya mahindi masika 2027, AGS-DEMO-LR27-00004. Lipa KES 4,070 kufikia 14/02/2027 (M-Pesa/SACCO). Piga *384*000#.','enrolled:d8a11ccf7812418d809dfe1b8bcf400d','logged','log',NULL,NULL,'2026-10-29 22:35:35.898949','2026-10-29 22:35:36.480446');
INSERT INTO "sms_message" VALUES(4,'85296c3b3d25486f982860996cf0383c','c171f6893b4e41ccbedcf016ec8237f7','enrolled','sw','AgroShield: Chebet, umesajiliwa bima ya mahindi masika 2027, AGS-DEMO-LR27-00005. Lipa KES 472 kufikia 14/02/2027 (M-Pesa/SACCO). Piga *384*000#.','enrolled:c171f6893b4e41ccbedcf016ec8237f7','logged','log',NULL,NULL,'2026-10-29 22:35:35.913952','2026-10-29 22:35:36.481474');
INSERT INTO "sms_message" VALUES(5,'a568f3f6b128464692c229804a6ffdcd','7dfc27a0a10a4a67a7819e8e33198d79','enrolled','en','AgroShield: Otieno, enrolled for long rains 2027 maize cover AGS-DEMO-LR27-00006. Pay KES 4,475 by 14/02/2027 (M-Pesa or SACCO). Dial *384*000#.','enrolled:7dfc27a0a10a4a67a7819e8e33198d79','logged','log',NULL,NULL,'2026-10-29 22:35:35.921141','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(6,'a78772c762ee43d89d48124867dc972f','8b7fe3c205944dda97e2c83aa866a340','cover_active','sw','AgroShield: ada imelipwa yote. Bima yako ya mahindi masika 2027 AGS-DEMO-LR27-00001 sasa inatumika. Malipo hufuata kipimo cha mvua cha wadi yako.','cover_active:8b7fe3c205944dda97e2c83aa866a340:DEMO-DED-0001','logged','log',NULL,NULL,'2026-10-29 22:35:35.921141','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(7,'60c86eab900044269448bfc32fc33c98','38034213c61a4f8e853956b81ad0d092','payment_received','en','AgroShield: received KES 1,599 for AGS-DEMO-LR27-00002. Paid KES 1,599 of 3,199. Balance KES 1,600, pay by 14/02/2027.','payment_received:38034213c61a4f8e853956b81ad0d092:SIM354CE4B9','logged','log',NULL,NULL,'2026-10-29 22:35:35.933956','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(8,'d2dbe41a49af4edb8fbd37926140de6d','d8a11ccf7812418d809dfe1b8bcf400d','payment_received','sw','AgroShield: tumepokea KES 1,000 kwa AGS-DEMO-LR27-00004. Umelipa KES 1,000 kati ya 4,070. Salio KES 3,070, lipa kabla ya 14/02/2027.','payment_received:d8a11ccf7812418d809dfe1b8bcf400d:DEMO-DED-0004','logged','log',NULL,NULL,'2026-10-29 22:35:35.939918','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(9,'a78772c762ee43d89d48124867dc972f','08353011bfc84f8eb328ebc7eedc5ac4','enrolled','sw','AgroShield: Wanjiku, umesajiliwa bima ya mahindi masika 2008, AGS-DEMO-LR08-00007. Lipa KES 1,753 kufikia 14/02/2008 (M-Pesa/SACCO). Piga *384*000#.','enrolled:08353011bfc84f8eb328ebc7eedc5ac4','logged','log',NULL,NULL,'2026-10-29 22:35:35.951958','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(10,'60c86eab900044269448bfc32fc33c98','5eb2801dcd404067a835489b9e1640a7','enrolled','en','AgroShield: Kiprono, enrolled for long rains 2008 maize cover AGS-DEMO-LR08-00008. Pay KES 3,199 by 14/02/2008 (M-Pesa or SACCO). Dial *384*000#.','enrolled:5eb2801dcd404067a835489b9e1640a7','logged','log',NULL,NULL,'2026-10-29 22:35:35.955069','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(11,'d2dbe41a49af4edb8fbd37926140de6d','d6aff0dab313420e8a3157b56aa3bf06','enrolled','sw','AgroShield: Mwangi, umesajiliwa bima ya mahindi masika 2008, AGS-DEMO-LR08-00010. Lipa KES 4,070 kufikia 14/02/2008 (M-Pesa/SACCO). Piga *384*000#.','enrolled:d6aff0dab313420e8a3157b56aa3bf06','logged','log',NULL,NULL,'2026-10-29 22:35:35.971613','2026-10-29 22:35:36.482474');
INSERT INTO "sms_message" VALUES(12,'a78772c762ee43d89d48124867dc972f','08353011bfc84f8eb328ebc7eedc5ac4','cover_active','sw','AgroShield: ada imelipwa yote. Bima yako ya mahindi masika 2008 AGS-DEMO-LR08-00007 sasa inatumika. Malipo hufuata kipimo cha mvua cha wadi yako.','cover_active:08353011bfc84f8eb328ebc7eedc5ac4:DEMO-2008-0','logged','log',NULL,NULL,'2026-10-29 22:35:35.971613','2026-10-29 22:35:36.483011');
INSERT INTO "sms_message" VALUES(13,'60c86eab900044269448bfc32fc33c98','5eb2801dcd404067a835489b9e1640a7','cover_active','en','AgroShield: premium paid in full. Your long rains 2008 maize cover AGS-DEMO-LR08-00008 is now active. Payouts follow your ward rainfall index.','cover_active:5eb2801dcd404067a835489b9e1640a7:DEMO-2008-1','logged','log',NULL,NULL,'2026-10-29 22:35:35.971613','2026-10-29 22:35:36.483011');
INSERT INTO "sms_message" VALUES(14,'d2dbe41a49af4edb8fbd37926140de6d','d6aff0dab313420e8a3157b56aa3bf06','lapsed','sw','AgroShield: AGS-DEMO-LR08-00010 haikulipwa yote kufikia 14/02/2008, kwa hivyo bima haikuanza. KES 0 utarudishiwa kupitia SACCO yako.','lapsed:d6aff0dab313420e8a3157b56aa3bf06','logged','log',NULL,NULL,'2026-10-29 22:35:36.070171','2026-10-29 22:35:36.483011');
INSERT INTO "sms_message" VALUES(15,'a78772c762ee43d89d48124867dc972f','08353011bfc84f8eb328ebc7eedc5ac4','payout_calculated','sw','AgroShield: ukame umethibitishwa katika wadi yako. Malipo KES 8,280 kwa AGS-DEMO-LR08-00007 yatalipwa kufikia 11/09/2008.','payout:1','logged','log',NULL,NULL,'2026-10-29 22:35:36.429294','2026-10-29 22:35:36.483011');
INSERT INTO "sms_message" VALUES(16,'60c86eab900044269448bfc32fc33c98','5eb2801dcd404067a835489b9e1640a7','payout_calculated','en','AgroShield: dry season confirmed in your ward. Payout KES 14,490 for AGS-DEMO-LR08-00008 will be paid by 11/09/2008.','payout:2','logged','log',NULL,NULL,'2026-10-29 22:35:36.432928','2026-10-29 22:35:36.483011');
INSERT INTO "sms_message" VALUES(17,'a78772c762ee43d89d48124867dc972f','08353011bfc84f8eb328ebc7eedc5ac4','payout_paid','sw','AgroShield: malipo KES 8,280 kwa AGS-DEMO-LR08-00007 yametumwa kwa M-Pesa yako, nambari SIMB2C1AC380C3.','paid:1','logged','log',NULL,NULL,'2026-10-29 22:35:36.434972','2026-10-29 22:35:36.483011');
INSERT INTO "sms_message" VALUES(18,'585fa9aa8d7e40cab55dbc201bb1897c','4287ffcd4767475b8ac915149e90ed81','enrolled','sw','AgroShield: Nafula, umesajiliwa bima ya mahindi masika 2027, AGS-DEMO2-LR27-00001. Lipa KES 2,685 kufikia 14/02/2027 (M-Pesa/SACCO). Piga *384*000#.','enrolled:4287ffcd4767475b8ac915149e90ed81','logged','log',NULL,NULL,'2026-10-29 22:35:36.443973','2026-10-29 22:35:36.484585');
INSERT INTO "sms_message" VALUES(19,'19d17f7f5cbe47758370752962744e4c','60121f393b2a4e108e57beb18c70d74c','enrolled','en','AgroShield: Kamau, enrolled for long rains 2027 maize cover AGS-DEMO2-LR27-00002. Pay KES 3,275 by 14/02/2027 (M-Pesa or SACCO). Dial *384*000#.','enrolled:60121f393b2a4e108e57beb18c70d74c','logged','log',NULL,NULL,'2026-10-29 22:35:36.451217','2026-10-29 22:35:36.485030');
CREATE TABLE ward_status (
	id INTEGER NOT NULL, 
	ward_id VARCHAR(40) NOT NULL, 
	season VARCHAR(4) NOT NULL, 
	year INTEGER NOT NULL, 
	as_of DATE NOT NULL, 
	data_through DATE, 
	mode VARCHAR(10) NOT NULL, 
	phase VARCHAR(20) NOT NULL, 
	level VARCHAR(10) NOT NULL, 
	projected_wrsi FLOAT, 
	projected_share FLOAT NOT NULL, 
	index_version VARCHAR(20) NOT NULL, 
	inputs_sha256 VARCHAR(64), 
	result JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "ward_status" VALUES(1,'ward-a','LR',2008,'2008-04-20','2008-04-19','replay','in_season','normal',100.0,0.0,'B-1.2.0','7f0740519698016a4e8929964c4802435591076820c2773de164829c901bb568','{"ward_id": "ward-a", "season": "LR", "year": 2008, "as_of": "2008-04-20", "data_through": "2008-04-19", "index_version": "B-1.2.0", "trigger_wrsi": 80.0, "exit_wrsi": 50.0, "window": ["2008-03-01", "2008-04-30"], "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "phase": "in_season", "level": "normal", "confirmed": [], "events": {}, "projected_wrsi": 100.0, "projected_share": 0.0, "failed_onset_projected": false, "sos": "Mar d3 2008", "sos_date": "2008-03-21", "sos_observed": true, "sos_rule": "planting rain", "season_end": "2008-07-31", "days_into_season": 29, "rain_since_window_mm": 115.1, "normal_since_window_mm": 166.7, "rain_pct_of_normal": 69, "window_rain_mm": 188.7, "inputs_sha256": "7f0740519698016a4e8929964c4802435591076820c2773de164829c901bb568", "dekads_observed": 5}','2026-10-29 22:35:36.071491');
INSERT INTO "ward_status" VALUES(2,'ward-a','LR',2008,'2008-06-01','2008-05-31','replay','in_season','watch',82.97,0.0,'B-1.2.0','ac4528d5e62dd8b27a32e4decbd2b172543c7cedc49a2d10ebe42cf1b5d3b3d2','{"ward_id": "ward-a", "season": "LR", "year": 2008, "as_of": "2008-06-01", "data_through": "2008-05-31", "index_version": "B-1.2.0", "trigger_wrsi": 80.0, "exit_wrsi": 50.0, "window": ["2008-03-01", "2008-04-30"], "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "phase": "in_season", "level": "watch", "confirmed": [], "events": {}, "projected_wrsi": 82.97, "projected_share": 0.0, "failed_onset_projected": false, "sos": "Mar d3 2008", "sos_date": "2008-03-21", "sos_observed": true, "sos_rule": "planting rain", "season_end": "2008-07-31", "days_into_season": 71, "rain_since_window_mm": 197.5, "normal_since_window_mm": 371.9, "rain_pct_of_normal": 53, "window_rain_mm": 151.8, "inputs_sha256": "ac4528d5e62dd8b27a32e4decbd2b172543c7cedc49a2d10ebe42cf1b5d3b3d2", "dekads_observed": 9}','2026-10-29 22:35:36.143942');
INSERT INTO "ward_status" VALUES(3,'ward-a','LR',2008,'2008-09-01','2008-08-31','replay','complete','payout',67.58,0.414,'B-1.2.0','a1e8aa7a91a133911c590e8335b7ebbd67e63a8f1dad319495feff528d2238c2','{"ward_id": "ward-a", "season": "LR", "year": 2008, "as_of": "2008-09-01", "data_through": "2008-08-31", "index_version": "B-1.2.0", "trigger_wrsi": 80.0, "exit_wrsi": 50.0, "window": ["2008-03-01", "2008-04-30"], "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "phase": "complete", "level": "payout", "confirmed": ["wrsi_final"], "events": {"wrsi_final": {"wrsi": 67.58, "share": 0.414}}, "projected_wrsi": 67.58, "projected_share": 0.414, "failed_onset_projected": false, "sos": "Mar d3 2008", "sos_date": "2008-03-21", "sos_observed": true, "sos_rule": "planting rain", "season_end": "2008-07-31", "days_into_season": 163, "rain_since_window_mm": 415.1, "normal_since_window_mm": 691.3, "rain_pct_of_normal": 60, "window_rain_mm": 151.8, "inputs_sha256": "a1e8aa7a91a133911c590e8335b7ebbd67e63a8f1dad319495feff528d2238c2", "dekads_observed": 18}','2026-10-29 22:35:36.213919');
INSERT INTO "ward_status" VALUES(4,'ward-a','LR',2027,'2026-10-30','2025-12-31','live','before_season','none',NULL,0.0,'B-1.2.0',NULL,'{"ward_id": "ward-a", "season": "LR", "year": 2027, "as_of": "2026-10-30", "data_through": "2025-12-31", "index_version": "B-1.2.0", "trigger_wrsi": 80.0, "exit_wrsi": 50.0, "window": ["2027-03-01", "2027-04-30"], "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "phase": "before_season", "level": "none", "confirmed": [], "projected_share": 0.0, "inputs_sha256": null}','2026-10-29 22:35:41.515769');
INSERT INTO "ward_status" VALUES(5,'ward-b','LR',2026,'2026-10-30','2025-12-31','live','data_unavailable','none',NULL,0.0,'B-1.2.0',NULL,'{"ward_id": "ward-b", "season": "LR", "year": 2026, "as_of": "2026-10-30", "data_through": "2025-12-31", "index_version": "B-1.2.0", "trigger_wrsi": 80.0, "exit_wrsi": 50.0, "window": ["2026-03-01", "2026-04-30"], "config_sha256": {"pilot.yaml": "622f69d948a92660063adc2f519993bdb2025602f599c0c4e671d7c767263966", "wards.yaml": "5d53a22fa76e715ea75dbd7341a4e6214c7fce1880d130828845a2d94f7be73f", "phenology.yaml": "5d36f0cdf5f2d3de7d471de242f3060bb3daf55945c6dc352fe9bdd0ca65f37b", "product.yaml": "9d83169771bf8496f5486eda074b638b2f35a07fb586bc644542185646520c6e"}, "phase": "data_unavailable", "level": "none", "confirmed": [], "projected_share": 0.0, "inputs_sha256": null}','2026-10-29 22:35:41.700992');
CREATE TABLE weather_fetch (
	id INTEGER NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	url VARCHAR(400) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	detail VARCHAR(300), 
	at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE weather_item (
	id INTEGER NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	source_label VARCHAR(40) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	url VARCHAR(400), 
	pdf_sha256 VARCHAR(64), 
	pdf_path VARCHAR(300), 
	text_excerpt TEXT, 
	valid_from DATE, 
	valid_to DATE, 
	origin VARCHAR(10) NOT NULL, 
	summary_en VARCHAR(480), 
	summary_sw VARCHAR(480), 
	status VARCHAR(12) NOT NULL, 
	approved_by VARCHAR(60), 
	approved_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (pdf_sha256)
);
CREATE INDEX ix_audit_event_at ON audit_event (at);
CREATE INDEX ix_ward_status_ward_id ON ward_status (ward_id);
CREATE INDEX ix_weather_fetch_source ON weather_fetch (source);
CREATE INDEX ix_premium_remittance_sacco_id ON premium_remittance (sacco_id);
CREATE INDEX ix_premium_remittance_insurer_id ON premium_remittance (insurer_id);
CREATE INDEX ix_farmer_phone_hash ON farmer (phone_hash);
CREATE INDEX ix_farmer_national_id_hash ON farmer (national_id_hash);
CREATE INDEX ix_policy_insurer_id ON policy (insurer_id);
COMMIT;
