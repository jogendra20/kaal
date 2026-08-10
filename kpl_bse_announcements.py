from bse import BSE

with BSE(download_folder='./') as bse:
    scripCode = bse.getScripCode('kirloskar pneumatic')
    print("Scrip code:", scripCode)

    data = bse.announcements(scripcode=scripCode)
    for item in data.get('Table', []):
        print(item.get('News_submission_dt', ''), '-', item.get('HEADLINE', ''))
