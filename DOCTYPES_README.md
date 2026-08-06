# Truck Service Center - DocTypes

## ภาพรวม

Truck Service Center เป็นแอป Frappe (ต้องติดตั้ง **ERPNext** ด้วย) สำหรับจัดการธุรกิจศูนย์บริการรถบรรทุก
ครอบคลุมตั้งแต่การ **นัดหมาย → เปิดใบสั่งงาน → ตัดสต็อก/ออกใบแจ้งหนี้** และการ **เสนอราคาซ่อม**
ตัวเลขเงินรองรับภาษีมูลค่าเพิ่ม (VAT รวม/แยก/ไม่คิด) และอะไหล่/บริการอ้างอิงกับ Item ของ ERPNext

> เอกสารที่เกี่ยวข้อง: [SETTINGS_README.md](SETTINGS_README.md) (การตั้งค่า singleton) และ [CLAUDE.md](CLAUDE.md) (สถาปัตยกรรม + คำสั่งสำหรับ dev)

## โครงสร้างเอกสารหลัก (Document Flow)

เอกสารธุรกรรม 3 ตัวต่อกันเป็น pipeline และใช้โครงสร้าง child table ชุดเดียวกัน:

```
Service Appointment (APT-.YYYY.-)   ── on_submit ──▶  Service Order (SO-.YYYY.-)  ◀── สร้างจาก ──  Repair Quotation (RQ-.YYYY.-)
   (นัดหมาย, ผูก slot)                                  (เอกสารหลัก, ตัดสต็อก/ออกบิล)              (ใบเสนอราคา)
```

child table ที่ทุกเอกสารใช้เหมือนกัน:
| บทบาท | Service Appointment | Service Order | Repair Quotation |
|---|---|---|---|
| ค่าแรง (labor) | `service_types` → Service Appointment Service Type | `service_types` → Service Order Service Type | `service_types` → Repair Quotation Service Type |
| อะไหล่ (parts) | `service_items` → Service Appointment Item | `service_items` → Service Order Item | `service_items` → Repair Quotation Item |
| แพ็คเกจ | `service_packages` → Service Appointment Package | `service_packages` → Service Order Package | `service_packages` → Repair Quotation Package |

**สถานะ submittable:** Service Appointment และ Service Order เป็น submittable; **Repair Quotation ไม่ submittable** (เป็น doctype ปกติ มี amended_from + naming series และจัดการสถานะเองผ่าน `update_status_on_save`)

---

## Master Data

### Vehicle (รถ)
`autoname = field:license_plate` — ทะเบียนรถเป็น Primary Key

เก็บข้อมูลรถบรรทุกของลูกค้า + ข้อมูลเทคนิค (เครื่องยนต์/เชื้อเพลิง/เกียร์/ยาง/ความจุน้ำมัน-น้ำยา/ไส้กรอง) + กำหนดบริการ (ระยะ กม./เดือน, เลขไมล์ครั้งถัดไป) + วันหมดอายุเอกสาร (ประกัน, ทะเบียน, ภาษี, ตรวจสภาพ)

**ฟิลด์สำคัญ:** `license_plate`, `truck_number`, `vehicle_type`, `customer`, `current_mileage`, `service_interval_km`, `service_interval_months`, `next_service_due`, `next_service_mileage`

**Methods:** `validate_mileage()` (กันเลขไมล์ย้อนหลัง), `calculate_next_service()`, `update_service_info()`, `get_service_history()`, `is_service_due()`, `get_upcoming_expirations()`
**แจ้งเตือนอัตโนมัติ:** scheduled task รายวัน ([tasks.py](truck_service_center/tasks.py)) แจ้งเอกสารใกล้หมดอายุและรถถึงกำหนดบริการถึง Service Manager/Service User ผ่าน Notification Log — เปิด/ปิดและตั้งจำนวนวันล่วงหน้าได้ใน Settings (ดู [SETTINGS_README.md](SETTINGS_README.md))
**Whitelisted:** `check_service_due`, `get_vehicle_service_history`, `get_customer_contact_info`, `get_vehicle_expirations`

### Service Type Group (กลุ่มบริการ)
`autoname = field:group_code`. ฟิลด์: `group_code`, `group_name`, `is_active`, `remark`
กลุ่มมาตรฐาน (seed จาก [fixtures/create_service_type_groups.py](truck_service_center/fixtures/create_service_type_groups.py)): SU100 เครื่องล่าง, EL100 ไฟฟ้า, TY100 ยาง, OT100 อื่นๆ, RM100 ระบบการทำงาน, TR100 ส่งกำลัง, WE100 เชื่อม, CH100 ตัวถัง

### Service Type (ประเภทบริการ)
`autoname = field:service_type_name`. กำหนดบริการ + ค่าแรง + อะไหล่มาตรฐานของบริการนั้น

**ฟิลด์สำคัญ:** `service_type_name`, `service_code`, `barcode` (รองรับสแกน), `maintenance_type` (PM/CM), `service_type_group`, `labor_rate`, `default_duration`, `item_code` (ผูก Item ของ ERPNext), `income_account`, `cost_center`, `items` (child → Service Type Item: อะไหล่มาตรฐาน)

**Methods:** `calculate_item_amounts()`, `set_labor_rate_from_item()`
**Whitelisted:** `bulk_update_item_prices(service_type_names)` (อัปเดตราคาอะไหล่หลายบริการพร้อมกันจาก Item Price), `get_item_price(item_code)`

### Repair Position (ตำแหน่งที่ซ่อม)
`autoname = field:position_code`. Master data ระบุตำแหน่งบนรถที่ซ่อม ใช้ใน child table service_types ของ Order/Quotation
ฟิลด์: `position_code` (เช่น EL01, EN00, SU01), `position_name`, `remark`, `is_active`
seed จาก [fixtures/repair_position_data.py](truck_service_center/fixtures/repair_position_data.py). กลุ่มรหัส: EL ไฟฟ้า, EN เครื่องยนต์, SU ช่วงล่าง, TY ยาง

### Service Appointment Slot (ช่วงเวลานัดหมาย)
`autoname = field:slot_name`. ฟิลด์: `slot_name`, `start_time`, `end_time`, `capacity` (จำนวนคันต่อ slot), `is_active`, `description`
seed จาก [setup_appointment_slots.py](truck_service_center/setup_appointment_slots.py). ใช้คุมความจุการนัดผ่าน `Service Appointment.check_slot_availability()`

---

## เอกสารธุรกรรม

### Service Appointment (ใบนัดหมาย) — submittable, `APT-.YYYY.-`
จองคิวบริการ ผูกกับ slot และดึงข้อมูลรถ/ลูกค้าอัตโนมัติ

**ฟิลด์สำคัญ:** `appointment_date`, `appointment_slot`, `appointment_start/end`, `status` (Scheduled/Confirmed/In Progress/Completed/Cancelled/No Show), `customer`, `vehicle`, `assigned_technician`, child tables (service_types/service_items/service_packages), ยอดรวม (`total_labor_charges`, `total_parts_amount`, `total_amount`), `service_order` (ลิงก์ย้อนกลับ)

**Methods:** `calculate_estimated_duration()`, `calculate_totals()`, `validate_appointment_datetime()`, `check_slot_availability()`, `sync_vehicle_info()`, `set_slot_datetimes()`, **`on_submit` → `create_service_order()`** (สร้าง Service Order จากใบนัด)
**Whitelisted:** `create_service_order_from_appointment`, `get_available_slots(date)`

### Service Order (ใบสั่งงานบริการ) — submittable, `SO-.YYYY.-` ⭐ เอกสารหลัก
หัวใจของระบบ จัดการงานซ่อม ตัดสต็อกอะไหล่ และออกใบแจ้งหนี้

**กลุ่มฟิลด์:**
- ข้อมูลรถ/ลูกค้า: `service_date`, `customer`, `vehicle`, `current_mileage` + ฟิลด์รถที่ดึงมา (`truck_number`, `brand`, `model`, `vin_number`, ฯลฯ) + ที่อยู่ (billing/shipping, `tax_id`)
- งานซ่อม: `service_packages`, `service_types`, `service_items`, `received_by`, `received_date`, `technician` ถึง `technician_4` (ช่าง 4 คน), `fuel_level_in/out`, `priority` (Low/Medium/High/Urgent), `estimated_time`, `actual_time`
- บาร์โค้ด: `scan_service_type_barcode`, `scan_item_barcode` (ยิงบาร์โค้ดเพื่อเพิ่มแถว)
- เงิน/ภาษี: `total_parts_amount`, `labor_charges`, `tax_type` (ราคารวม VAT/ราคาแยก VAT/ไม่คิด VAT), `vat_rate`, `discount_amount`, `net_total`, `tax_amount`, `total_amount`
- การชำระเงิน: `payment_status` (Unpaid/Partially Paid/Paid), `payment_method`, `paid_amount`, `outstanding_amount` — สามฟิลด์สถานะ/ยอดเป็น **read-only ระบบคุมเอง**: รับชำระผ่านปุ่ม "รับชำระเงิน" (สร้าง Payment Entry จาก Sales Invoice) แล้ว doc_events ใน hooks.py ซิงค์ยอดจากใบแจ้งหนี้กลับมาอัตโนมัติเมื่อ Payment Entry / Journal Entry / Sales Invoice ถูก submit หรือ cancel (`sync_payment_from_sales_invoice`)
- ภาษีหัก ณ ที่จ่าย (WHT): `apply_wht` (ติ๊กอัตโนมัติเมื่อลูกค้าเป็นนิติบุคคล/Company), `wht_rate` (default 3%), `wht_base` (ค่าแรงเท่านั้น = แยกบิล / ทั้งใบ = จ้างเหมา), `wht_amount`, `net_payment_amount` (ยอดรับชำระสุทธิ), `wht_certificate_no/date` (บันทึกใบ 50 ทวิ ได้หลัง submit) — คำนวณจาก**ยอดก่อน VAT** ใน `calculate_wht()` (เฉลี่ยส่วนลดท้ายบิลตามสัดส่วน, ถอด VAT ถ้าราคารวม VAT) และตอนกด "รับชำระเงิน" ระบบใส่แถวหัก (Deductions → `wht_account` จาก Settings) ใน Payment Entry ให้: รับเงินจริงน้อยลงแต่ปิดหนี้เต็มจำนวน (ถ้ามีการชำระบางส่วนก่อนแล้วต้องใส่ deduction เอง)
- ลิงก์ ERPNext: `sales_invoice`, `stock_entry`
- สถานะ: `status` (Draft/In Progress/Completed/Cancelled/On Hold)

**Methods:** `apply_service_packages()`, `set_tax_defaults()`, `calculate_totals()` (รวมค่าแรงทุกบรรทัด + VAT ตาม tax_type; แถวอะไหล่ที่ไม่มีราคาใช้ `get_default_selling_rate()`: Item Price → standard_rate → ราคาทุนเป็นทางสุดท้าย), `calculate_wht()`, `update_payment_status()`, `update_material_issue_status()`, `update_vehicle_info()` (อัปเดตเลขไมล์/กำหนดบริการของรถ), `revert_vehicle_info()` (**on_cancel** — คืนข้อมูลบริการของรถจากใบงานที่เหลือ หรือล้างถ้าไม่มี), `create_sales_invoice()`, `complete_linked_service_appointment()` (ปิดใบนัดเมื่อ submit)

**Material Issue (ตัดสต็อกแยกราย Item):** อะไหล่แต่ละแถวมี `warehouse`, `material_issue` (ลิงก์ Stock Entry), `material_issue_status` — จัดการผ่าน whitelisted `create_material_issue`, `sync_material_issue`, `get_material_issue_summary`, และ `check_material_issues_before_submit` (กัน submit ถ้ายังไม่ได้เบิกครบ)
**Whitelisted อื่น:** `get_item_rate`, `get_item_by_barcode`, `receive_vehicle`, `get_service_type_items`, `create_sales_invoice_from_service_order`

**Workflow:**
1. สร้าง Service Order (เลือกรถ → ดึงข้อมูลลูกค้า/รถ/ที่อยู่อัตโนมัติ) หรือถูกสร้างจาก Appointment/Quotation
2. เลือกแพ็คเกจ (auto-load บริการ+อะไหล่) หรือเพิ่ม service_types / service_items เอง (พิมพ์หรือยิงบาร์โค้ด)
3. เบิกอะไหล่ด้วยปุ่ม "Create Material Issue" (สร้าง Stock Entry ประเภท Material Issue) — ต้องกดเอง ไม่มีการสร้างอัตโนมัติ และต้อง submit ใบเบิกให้ครบก่อนจึงจะ submit ใบสั่งงานได้
4. Submit → ปิดใบนัดที่ผูกอยู่ + อัปเดตข้อมูลรถ
5. สร้าง Sales Invoice (auto-submit ได้ตาม Settings)
6. กด "รับชำระเงิน" → สร้าง Payment Entry (draft) จากใบแจ้งหนี้ → ตรวจสอบ/Submit ที่หน้า Payment Entry → สถานะชำระเงินบน Service Order อัปเดตเอง (จะกดซ้ำได้จนกว่าจะ Paid — รองรับชำระบางส่วน)

### Repair Quotation (ใบเสนอราคาซ่อม) — `RQ-.YYYY.-` (ไม่ submittable)
เสนอราคางานซ่อมก่อนเปิดใบสั่งงาน

**ฟิลด์สำคัญ:** `quotation_date`, `valid_until`, `status` (Draft/Open/Accepted/Rejected/Expired/Cancelled), `customer`, `vehicle` + ข้อมูลรถ/ที่อยู่, child tables (service_types/service_items/service_packages), เงิน/ภาษีชุดเดียวกับ Service Order, `customer_complaints` (อาการที่แจ้ง), `recommendations`, `service_order` (ลิงก์เมื่อแปลงเป็นใบสั่งงาน)

**Methods:** `set_tax_defaults()`, `apply_service_packages()`, `calculate_totals()`, `validate_valid_until()`, `update_status_on_save()`
**Whitelisted:** `create_service_order_from_quotation`, `get_item_rate`, `get_item_by_barcode`

---

## Service Package (แพ็คเกจบริการ)
`autoname = field:package_code`. รวมหลายบริการ + อะไหล่ เป็นแพ็คเกจราคาพิเศษ เลือกใน Order/Appointment/Quotation แล้ว auto-load รายการ

**ฟิลด์สำคัญ:** `package_code`, `package_name`, `package_type` (Standard/Premium/Basic/Custom), `is_active`, `package_service_types` (child → Service Package Service Type: บริการ+ค่าแรง), `package_parts` (child → Service Package Part: อะไหล่), ราคา (`total_labor_rate`, `total_parts_amount`, `total_standard_rate`, `discount_percent`, `package_rate`), เงื่อนไข (`validity_days`, `service_interval_km`, `max_services`)

**Methods:** `validate_package_service_types()`, `populate_parts_from_service_types()` (ดึงอะไหล่มาตรฐานจาก Service Type มาเป็น package_parts ให้อัตโนมัติ), `calculate_totals()`, `validate_pricing()`, `get_discount_amount()`
**Whitelisted:** `get_package_details(package_name)`, `get_active_packages()`

---

## Truck Service Center Settings (singleton)
ควบคุมพฤติกรรมการตัดสต็อก/ออกบิล/ภาษีทั้งระบบ — ดูรายละเอียดที่ [SETTINGS_README.md](SETTINGS_README.md)
ประเด็นสำคัญ: ต้องตั้ง **Labor Item** ก่อนจึงจะออก Sales Invoice ที่มีค่าแรงได้ (มีปุ่ม "Create Labor Item" / whitelisted `create_labor_item`); toggle `auto_submit_sales_invoice`; เทมเพลตภาษี (`vat_inclusive_template` / `vat_exclusive_template`) จับคู่กับ `tax_type` ของเอกสารผ่าน `get_tax_template_for_type()`

---

## Integration กับ ERPNext

- **Stock:** อะไหล่อ้างอิง `Item`/`Warehouse`/`UOM`; เบิกอะไหล่ผ่าน `Stock Entry` (Material Issue)
- **Sales:** ใช้ `Customer`/`Address`; ออก `Sales Invoice` (ค่าแรงลงผ่าน Labor Item, อะไหล่ลงตามรายการ)
- **Accounting:** `Account` / `Cost Center` / `Sales Taxes and Charges Template` / `Payment Terms Template`
- **ราคา:** ดึงจาก `Item Price` / Price List ของลูกค้า (`get_item_rate`)

---

## รายงาน (Script Reports)

อยู่ใน [truck_service_center/report/](truck_service_center/truck_service_center/report/) — เข้าจาก section "รายงาน" ใน workspace/sidebar หรือ awesomebar

| Report | เนื้อหา | สิทธิ์เพิ่มเติม |
|---|---|---|
| **Vehicle Service History** (ประวัติการซ่อมรายคัน) | Service Order ทุกใบของรถ/ลูกค้า พร้อมงานที่ทำ ยอดเงิน สถานะชำระ | Technician |
| **Revenue by Service Group** (รายได้ตามกลุ่มบริการ) | ค่าแรงแยกตาม Service Type Group + แถวรวมอะไหล่ พร้อม % และ bar chart (จากใบงาน submit แล้ว, ยอดหลังส่วนลดรายการ ก่อนส่วนลดท้ายบิล/VAT) | Accounts User |
| **Customer Outstanding Summary** (ยอดค้างชำระรายลูกค้า) | ใบงานค้างชำระ group ตามลูกค้า: ยอดรวม/ชำระแล้ว/ค้าง, ยังไม่ออกบิลกี่ใบ, ค้างนานกี่วัน | Accounts User |
| **Technician Performance** (ประสิทธิภาพช่าง) | จำนวนใบงาน เวลาประเมิน vs เวลาจริง ประสิทธิภาพ (%) ยอดงานที่มีส่วนร่วม — ใบงานที่ทำร่วมกันนับให้ช่างทุกคนเต็มใบ | Technician |

ทุกรายงานมี Service Manager / Service User / System Manager เป็นฐาน

---

## การใช้งาน (เมนูใน Desk)

Workspace **Truck Service Center** จัดกลุ่ม sidebar เป็น Service Operations / Master Data / รายงาน / Admin & Settings
(โครงสร้างเมนูแก้ที่ doctype *Workspace Sidebar* — ดู [CLAUDE.md](CLAUDE.md) หัวข้อ Workspace & Sidebar)

- **เพิ่มรถ:** Vehicle → New
- **นัดหมาย:** Service Appointment → New (เลือก slot + รถ) → Submit จะสร้าง Service Order ให้
- **เปิดใบสั่งงาน:** Service Order → New หรือสร้างจาก Appointment/Quotation
- **เสนอราคา:** Repair Quotation → New → เมื่อรับงานกด สร้าง Service Order
- **แพ็คเกจ:** Service Package → New

---

## บทบาทและสิทธิ์ผู้ใช้ (Roles & Permissions)

Role ของแอป (seed จาก `create_default_roles()` ใน [install.py](truck_service_center/install.py) — รันอัตโนมัติตอน install; site เดิมรันเองด้วย `bench --site <site> execute truck_service_center.install.create_default_roles`):

| Role | บทบาท |
|---|---|
| **Service Manager** | ผู้จัดการศูนย์ — สิทธิ์เต็มทุก doctype รวมถึง cancel/delete และแก้ Settings |
| **Service User** | ธุรการ/Service Advisor — รับรถ นัดหมาย เสนอราคา เปิด+submit ใบสั่งงาน ลงทะเบียนรถ |
| **Technician** | ช่าง — อ่านข้อมูลทั่วไป และแก้ไข Service Order (อัพเดทงาน/เวลาจริง) แต่สร้าง/submit ไม่ได้ |

และใช้ role มาตรฐานของ ERPNext เพิ่มเติม: **Stock User** (อ่าน Service Order เพื่อเบิกอะไหล่), **Accounts User** (อ่าน Service Order + Repair Quotation เพื่อออกบิล)

### Permission matrix (สรุป)

| Doctype | Service Manager | Service User | Technician | Stock User | Accounts User |
|---|---|---|---|---|---|
| Service Order | ทั้งหมด + submit/cancel | create/write/submit | read/write | read | read |
| Service Appointment | ทั้งหมด + submit/cancel | create/write/submit/cancel | read | — | — |
| Repair Quotation | ทั้งหมด | create/write | — | — | read |
| Vehicle | ทั้งหมด | create/write | read | — | — |
| Vehicle Brand | ทั้งหมด | create/read | read | — | — |
| Master data อื่น (Service Type/Group, Repair Position, Package, Slot) | ทั้งหมด | read | read | — | — |
| Truck Service Center Settings | read/write | — | — | — | — |

หมายเหตุ: การ **cancel Service Order** สงวนให้ Service Manager (Service User submit ได้แต่ยกเลิกไม่ได้) และ whitelisted endpoint ทุกตัว (เช่น `receive_vehicle`, `create_material_issue`, `create_sales_invoice_from_service_order`) มี `check_permission` ตรวจสิทธิ์ตามตารางนี้ก่อนทำงานเสมอ

## License
MIT
