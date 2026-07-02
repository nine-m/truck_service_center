# Truck Service Center Settings

## การตั้งค่า

เข้าไปที่: **Setup → Truck Service Center Settings**

### การตั้งค่าทั่วไป

#### บริษัทเริ่มต้น (Default Company)
- เลือกบริษัทที่จะใช้เป็นค่าเริ่มต้นในการสร้างเอกสาร

#### คลังสินค้าเริ่มต้น (Default Warehouse)
- คลังที่จะใช้เป็นค่าเริ่มต้นในการเบิกอะไหล่

---

### การตั้งค่าค่าแรงงาน (Labor Settings)

#### รายการสินค้าสำหรับค่าแรง (Labor Item) ⚠️ **จำเป็น**
- เลือก Item ที่จะใช้บันทึกค่าแรงในใบแจ้งหนี้
- **หากไม่ตั้งค่า จะไม่สามารถสร้าง Sales Invoice ที่มีค่าแรงได้**
- กดปุ่ม **"Create Labor Item"** เพื่อสร้างอัตโนมัติ

#### บัญชีค่าใช้จ่ายค่าแรง (Labor Expense Account)
- บัญชีที่จะบันทึกค่าใช้จ่ายค่าแรง
- แนะนำ: Direct Expenses → Labor Charges

#### ศูนย์ต้นทุนค่าแรง (Labor Cost Center)
- ศูนย์ต้นทุนสำหรับค่าแรง

---

### การตั้งค่าคลังสินค้า (Stock Settings)

#### สร้าง Stock Entry อัตโนมัติเมื่อ Submit
- ✅ เปิด: สร้าง Stock Entry อัตโนมัติเมื่อ Submit Service Order
- ❌ ปิด: ต้องสร้าง Stock Entry เอง

#### คลังต้นทางเริ่มต้น (Default Source Warehouse)
- คลังที่จะตัดสต็อกอะไหล่

#### บัญชีค่าใช้จ่ายเริ่มต้น (Default Expense Account)
- บัญชีสำหรับบันทึกค่าใช้จ่ายอะไหล่

#### ศูนย์ต้นทุนเริ่มต้น (Default Cost Center)
- ศูนย์ต้นทุนเริ่มต้น

---

### การตั้งค่าใบแจ้งหนี้ (Invoice Settings)

#### Submit Sales Invoice อัตโนมัติ
- ✅ เปิด: Submit Sales Invoice ทันทีหลังสร้าง
- ❌ ปิด: สร้างเป็น Draft ให้ตรวจสอบก่อน Submit

#### Series ใบแจ้งหนี้ (Sales Invoice Series)
- กำหนด Series สำหรับเลขที่ใบแจ้งหนี้
- ตัวอย่าง: `SINV-.YYYY.-`

#### เงื่อนไขการชำระเงินเริ่มต้น (Payment Terms Template)
- เลือก Payment Terms Template เริ่มต้น

#### บัญชีรายได้เริ่มต้น (Default Income Account)
- บัญชีรายได้จากการให้บริการ

---

### การตั้งค่าภาษีมูลค่าเพิ่ม (VAT / Tax Settings)

เอกสาร (Service Order / Repair Quotation) มีฟิลด์ `tax_type` ให้เลือก 3 แบบ ค่าตั้งต้นและเทมเพลตภาษีกำหนดที่นี่

#### ประเภทภาษีเริ่มต้น (Default Tax Type)
- `ราคารวม VAT` (VAT inclusive) — ราคาที่กรอกรวม VAT แล้ว
- `ราคาแยก VAT` (VAT exclusive) — บวก VAT เพิ่มจากยอด
- `ไม่คิด VAT` — ไม่มีภาษี

#### อัตรา VAT (VAT Rate %)
- อัตราภาษีมาตรฐาน (เช่น 7)

#### เทมเพลตภาษี (Tax Templates) ⚠️ จำเป็นถ้าจะออก Sales Invoice ที่มี VAT
- **เทมเพลต ราคาแยก VAT** (`vat_exclusive_template`) → Sales Taxes and Charges Template สำหรับ VAT exclusive
- **เทมเพลต ราคารวม VAT** (`vat_inclusive_template`) → Template สำหรับ VAT inclusive
- ระบบจับคู่ `tax_type` ของเอกสารกับเทมเพลตที่ถูกต้องอัตโนมัติเมื่อสร้าง Sales Invoice (ผ่าน `get_tax_template_for_type()`)
- `validate_tax_templates()` จะตรวจความถูกต้องของเทมเพลตตอนบันทึก Settings

---

### การแจ้งเตือนอัตโนมัติ (Notification Settings)

ควบคุม scheduled task รายวัน (ดู `scheduler_events` ใน hooks.py และ [tasks.py](truck_service_center/tasks.py)) — แจ้งเตือนเป็น Notification Log (กระดิ่งใน Desk) ถึงผู้ใช้ role **Service Manager** และ **Service User** เหตุการณ์เดียวกันแจ้งครั้งเดียวจนกว่าวันครบกำหนดจะเปลี่ยน (เช่น ต่อประกันแล้ว)

#### แจ้งเตือนเอกสารรถใกล้หมดอายุ (`enable_expiry_notifications`)
- ตรวจรถสถานะ Active ที่ ประกันภัย / ทะเบียนรถ / ภาษีรถ / ตรวจสภาพรถ ใกล้หมดอายุหรือหมดอายุแล้ว
- **แจ้งล่วงหน้า (วัน)** (`expiry_notice_days`) — ค่าเริ่มต้น 30 วัน

#### แจ้งเตือนรถถึงกำหนดบริการ (`enable_service_due_notifications`)
- ตรวจตาม `next_service_due` (วันที่) และ `next_service_mileage` เทียบเลขไมล์ปัจจุบัน
- **แจ้งล่วงหน้า (วัน)** (`service_due_notice_days`) — ค่าเริ่มต้น 7 วัน

> นอกจากแจ้งเตือน scheduler ยังเปลี่ยนสถานะ **Repair Quotation** ที่เลย `valid_until` จาก Open → Expired ให้อัตโนมัติทุกวัน (อันนี้ไม่มี toggle)
> ค่าเริ่มต้นถูกเติมลง DB โดย patch `set_notification_defaults` — toggle ที่ยังไม่เคยบันทึก (NULL) ถือว่าเปิดใช้งาน

---

## วิธีตั้งค่าครั้งแรก

### 1. สร้าง Labor Item (ค่าแรง)
```
1. ไปที่ Setup → Truck Service Center Settings
2. กดปุ่ม "Create Labor Item" 
3. ระบบจะสร้าง Item "Labor Charge" อัตโนมัติ
4. Item จะถูกเลือกในช่อง "รายการสินค้าสำหรับค่าแรง"
```

### 2. ตั้งค่าบัญชี (Accounts)
```
1. กำหนด Labor Expense Account
2. กำหนด Default Expense Account
3. กำหนด Default Income Account
```

### 3. ตั้งค่าคลัง (Warehouse)
```
1. กำหนด Default Warehouse
2. กำหนด Default Source Warehouse
```

### 4. ตั้งค่าศูนย์ต้นทุน (Cost Center)
```
1. กำหนด Default Cost Center
2. กำหนด Labor Cost Center (ถ้าต้องการแยก)
```

### 5. ตั้งค่าภาษี (VAT) — ถ้าต้องออกบิลมี VAT
```
1. เลือก Default Tax Type และ VAT Rate
2. กำหนด เทมเพลต ราคาแยก VAT และ/หรือ ราคารวม VAT
   (Sales Taxes and Charges Template ของ ERPNext)
```

---

## การใช้งาน

### เมื่อสร้าง Service Order
- ระบบจะใช้ค่าจาก Settings เป็นค่าเริ่มต้น
- สามารถแก้ไขในแต่ละเอกสารได้

### เมื่อสร้าง Sales Invoice
- ถ้ามีค่าแรง แต่ยังไม่ได้ตั้งค่า Labor Item
- ระบบจะแสดงข้อความ:
  ```
  กรุณาตั้งค่า 'รายการสินค้าสำหรับค่าแรง' ใน 
  Truck Service Center Settings ก่อนสร้าง Sales Invoice
  ```

---

## คำแนะนำ

### ⚠️ สิ่งที่ต้องตั้งค่าก่อนใช้งาน
1. ✅ Labor Item (จำเป็น)
2. ✅ Default Company
3. ✅ Labor Expense Account (แนะนำ)

### 💡 สิ่งที่ตั้งค่าได้ภายหลัง
- Default Warehouse
- Default Cost Center
- Payment Terms Template
- Auto Submit Sales Invoice
- VAT Templates (จำเป็นเฉพาะเมื่อต้องออกบิลมี VAT)

---

## Troubleshooting

### ❌ ไม่สามารถสร้าง Sales Invoice ได้
**สาเหตุ:** ยังไม่ได้ตั้งค่า Labor Item

**วิธีแก้:**
1. ไปที่ Truck Service Center Settings
2. กดปุ่ม "Create Labor Item"
3. หรือเลือก Item ที่มีอยู่แล้ว

### ❌ บัญชีไม่ถูกต้อง
**สาเหตุ:** ยังไม่ได้ตั้งค่าบัญชี

**วิธีแก้:**
1. ตรวจสอบ Chart of Accounts
2. เลือกบัญชีที่เหมาะสมใน Settings

---

## License

MIT
