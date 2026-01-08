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
