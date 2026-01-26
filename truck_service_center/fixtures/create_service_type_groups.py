import frappe

def create_service_type_groups():
    """สร้างข้อมูล Service Type Group ตัวอย่าง"""
    groups = [
        {'group_code': 'EL100', 'group_name': 'ไฟฟ้า'},
        {'group_code': 'TY100', 'group_name': 'ยาง'},
        {'group_code': 'OT100', 'group_name': 'อื่นๆ'},
        {'group_code': 'RM100', 'group_name': 'ระบบการทำงานของรถ'},
        {'group_code': 'TR100', 'group_name': 'ส่งกำลัง'},
        {'group_code': 'WE100', 'group_name': 'เชื่อม'},
        {'group_code': 'CH100', 'group_name': 'ตัวถัง'}
    ]
    
    created = 0
    for group_data in groups:
        try:
            if not frappe.db.exists('Service Type Group', group_data['group_code']):
                doc = frappe.get_doc({
                    'doctype': 'Service Type Group',
                    'group_code': group_data['group_code'],
                    'group_name': group_data['group_name'],
                    'is_active': 1
                })
                doc.insert()
                created += 1
                print(f"✓ สร้าง {group_data['group_code']} - {group_data['group_name']}")
        except Exception as e:
            print(f"✗ ข้อผิดพลาด {group_data['group_code']}: {str(e)}")
    
    if created > 0:
        frappe.db.commit()
    
    print(f"\n✓ สร้างข้อมูล Service Type Group เรียบร้อย ({created} รายการ)")

if __name__ == "__main__":
    create_service_type_groups()
