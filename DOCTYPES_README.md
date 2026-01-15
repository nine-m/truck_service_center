# Truck Service Center - DocTypes

## ภาพรวม

Truck Service Center เป็นแอปพลิเคชันสำหรับจัดการธุรกิจศูนย์บริการรถบรรทุก รองรับการบริการต่างๆ เช่น:
- เปลี่ยนถ่ายน้ำมันเครื่อง
- เช็คระยะ
- เปลี่ยนยาง
- ซ่อมบำรุงทั่วไป

## DocTypes ที่สร้าง

### 1. Vehicle (รถ)
**Path:** `truck_service_center/doctype/vehicle/`

**คุณสมบัติ:**
- จัดเก็บข้อมูลรถบรรทุกของลูกค้า
- ติดตามเลขไมล์และกำหนดการบริการ
- แจ้งเตือนเอกสารหมดอายุ (ประกัน, ทะเบียน, ภาษี, ตรวจสภาพ)
- บันทึกข้อมูลทางเทคนิค (เครื่องยนต์, เชื้อเพลิง, ยาง)

**ฟิลด์สำคัญ:**
- `license_plate` - ทะเบียนรถ (Primary Key)
- `customer` - ลูกค้าเจ้าของรถ (Link to Customer)
- `current_mileage` - เลขไมล์ปัจจุบัน
- `next_service_due` - วันที่ครบกำหนดบริการ
- `next_service_mileage` - เลขไมล์ที่ควรเข้าบริการ

**Methods:**
- `validate_mileage()` - ตรวจสอบเลขไมล์ไม่ย้อนหลัง
- `calculate_next_service()` - คำนวณกำหนดบริการครั้งถัดไป
- `update_service_info()` - อัพเดทข้อมูลหลังการบริการ
- `is_service_due()` - ตรวจสอบว่าถึงกำหนดบริการหรือไม่
- `get_upcoming_expirations()` - ดึงรายการเอกสารที่ใกล้หมดอายุ

---

### 2. Service Type (ประเภทบริการ)
**Path:** `truck_service_center/doctype/service_type/`

**คุณสมบัติ:**
- กำหนดประเภทบริการต่างๆ
- ตั้งราคามาตรฐานและค่าแรง
- เชื่อมโยงกับ Item ใน ERPNext

**ฟิลด์สำคัญ:**
- `service_type_name` - ชื่อประเภทบริการ (Primary Key)
- `default_rate` - ราคามาตรฐาน
- `labor_rate` - ค่าแรง
- `default_duration` - ระยะเวลาทำงานโดยประมาณ
- `item_code` - เชื่อมโยงกับ Item (Link to Item)

**ตัวอย่างประเภทบริการ:**
- เปลี่ยนถ่ายน้ำมันเครื่อง
- เช็คระยะ 10,000 กม.
- เปลี่ยนยาง
- ตรวจเช็คระบบเบรก
- เปลี่ยนไส้กรองอากาศ

---

### 3. Service Order (ใบสั่งงานบริการ)
**Path:** `truck_service_center/doctype/service_order/`

**คุณสมบัติ:**
- ใบสั่งงานหลักสำหรับการบริการ
- รองรับการ Submit/Cancel
- สร้าง Stock Entry อัตโนมัติเมื่อ submit
- อัพเดทข้อมูลรถอัตโนมัติ
- สามารถสร้าง Sales Invoice

**ฟิลด์สำคัญ:**
- `naming_series` - รหัสใบสั่งงาน (SO-.YYYY.-)
- `service_date` - วันที่เข้าบริการ
- `customer` - ลูกค้า (Link to Customer)
- `vehicle` - รถ (Link to Vehicle)
- `current_mileage` - เลขไมล์ปัจจุบัน
- `service_type` - ประเภทบริการ (Link to Service Type)
- `service_items` - รายการบริการและอะไหล่ (Table)
- `total_amount` - ยอดรวมทั้งหมด
- `status` - สถานะ (Draft, In Progress, Completed, Cancelled, On Hold)

**Methods:**
- `calculate_totals()` - คำนวณยอดรวม
- `update_payment_status()` - อัพเดทสถานะการชำระเงิน
- `create_stock_entry()` - สร้าง Stock Entry ตัดสต็อก
- `update_vehicle_info()` - อัพเดทข้อมูลรถ
- `create_sales_invoice()` - สร้างใบแจ้งหนี้

**Workflow:**
1. สร้าง Service Order (Draft)
2. เพิ่มรายการบริการและอะไหล่
3. Submit → สร้าง Stock Entry และอัพเดทข้อมูลรถ
4. สร้าง Sales Invoice (ถ้าต้องการ)

---

### 4. Service Order Item (รายการบริการ - Child Table)
**Path:** `truck_service_center/doctype/service_order_item/`

**คุณสมบัติ:**
- Child table สำหรับเก็บรายการบริการและอะไหล่
- เชื่อมโยงกับ Item ใน ERPNext
- รองรับการตัดสต็อกจาก Warehouse

**ฟิลด์สำคัญ:**
- `item_code` - รหัสสินค้า (Link to Item)
- `qty` - จำนวน
- `rate` - ราคาต่อหน่วย
- `amount` - ยอดรวม (คำนวณอัตโนมัติ)
- `warehouse` - คลังสินค้า (Link to Warehouse)
- `expense_account` - บัญชีค่าใช้จ่าย

---

### 5. Service Package (แพ็คเกจบริการ)
**Path:** `truck_service_center/doctype/service_package/`

**คุณสมบัติ:**
- สร้างแพ็คเกจบริการที่รวมบริการหลายรายการ
- กำหนดราคาพิเศษและส่วนลด
- ตั้งค่าเงื่อนไขการใช้งาน (ระยะเวลา, ระยะทาง, จำนวนครั้ง)
- เชื่อมโยงกับ Service Order โดยอัตโนมัติ

**ฟิลด์สำคัญ:**
- `package_name` - ชื่อแพ็คเกจ (Primary Key)
- `package_type` - ประเภทแพ็คเกจ (Standard, Premium, Basic, Custom)
- `is_active` - เปิด/ปิดใช้งาน
- `package_items` - รายการบริการในแพ็คเกจ (Child Table)
- `total_standard_rate` - ราคามาตรฐานรวม (คำนวณอัตโนมัติ)
- `discount_percent` - ส่วนลด (%)
- `package_rate` - ราคาแพ็คเกจ (หลังหักส่วนลด)
- `validity_days` - ระยะเวลาใช้งาน (วัน)
- `service_interval_km` - ระยะทางระหว่างบริการ (กม.)
- `max_services` - จำนวนครั้งบริการสูงสุด

**Methods:**
- `calculate_totals()` - คำนวณยอดรวมและส่วนลด
- `get_package_items_for_service_order()` - ดึงรายการบริการสำหรับ Service Order
- `get_discount_amount()` - คำนวณจำนวนเงินส่วนลด

**ตัวอย่างแพ็คเกจ:**
- แพ็คเกจบำรุงรักษาพื้นฐาน (เปลี่ยนถ่ายน้ำมัน + ไส้กรอง)
- แพ็คเกจตรวจเช็คประจำปี (ตรวจสอบระบบทั้งหมด + เปลี่ยนถ่ายน้ำมัน)
- แพ็คเกจพรีเมียม (บริการครบวงจร พร้อมของแถม)

**Integration กับ Service Order:**
- เลือกแพ็คเกจใน Service Order จะโหลดรายการบริการอัตโนมัติ
- ราคาจะถูกคำนวณตามส่วนลดที่กำหนดในแพ็คเกจ

---

## การใช้งาน

### 1. เพิ่มรถใหม่
```
Desk → Truck Service Center → Vehicle → New
- กรอกทะเบียนรถ
- เลือกลูกค้า
- กรอกข้อมูลรถ
- ตั้งค่าระยะบริการ
```

### 2. สร้างใบสั่งงานบริการ
```
Desk → Truck Service Center → Service Order → New
- เลือกรถ (จะดึงข้อมูลลูกค้าอัตโนมัติ)
- กรอกเลขไมล์ปัจจุบัน
- เลือกแพ็คเกจบริการ (ถ้ามี) หรือเลือกประเภทบริการ
- เพิ่มรายการบริการและอะไหล่
- Submit เมื่อทำงานเสร็จ
```

### 3. สร้างแพ็คเกจบริการ
```
Desk → Truck Service Center → Service Package → New
- ตั้งชื่อแพ็คเกจ
- เลือกประเภทแพ็คเกจ
- เพิ่มรายการบริการและอะไหล่
- กำหนดส่วนลดและราคา
- ตั้งค่าเงื่อนไขการใช้งาน (ถ้าต้องการ)
```

### 4. ตรวจสอบรถที่ถึงกำหนดบริการ
```
Report → Truck Service Center → Service Due Report
```

## Integration กับ ERPNext

### Stock Management
- ใช้ **Item** จาก ERPNext เพื่อจัดการอะไหล่
- ใช้ **Warehouse** เพื่อจัดการคลังสินค้า
- สร้าง **Stock Entry** อัตโนมัติเมื่อทำงานเสร็จ

### Customer & Sales
- ใช้ **Customer** จาก ERPNext
- สร้าง **Sales Invoice** สำหรับเก็บเงิน

### Accounting
- ใช้ **Account** และ **Cost Center** จาก ERPNext
- บันทึกบัญชีอัตโนมัติผ่าน Sales Invoice

## ฟีเจอร์ที่ควรเพิ่มในอนาคต

- [ ] Service Reminder (ส่งอีเมลแจ้งเตือนเมื่อถึงกำหนดบริการ)
- [ ] Technician Management (จัดการช่างและตารางงาน)
- [x] Service Package (แพ็คเกจบริการ) - ✅ พัฒนาเสร็จแล้ว
- [ ] Warranty Management (จัดการการรับประกัน)
- [ ] Parts Recommendation (แนะนำอะไหล่ตามระยะทาง)
- [ ] Dashboard & Analytics (สถิติและกราฟ)
- [ ] Customer Portal (ลูกค้าดูประวัติรถออนไลน์)
- [ ] Mobile App Integration

## ติดตั้ง

App นี้ติดตั้งและพร้อมใช้งานแล้ว:

```bash
# ตรวจสอบ app ที่ติดตั้ง
bench --site [site-name] list-apps

# Migrate database (ถ้าต้องการ)
bench --site [site-name] migrate
```

## License

MIT
