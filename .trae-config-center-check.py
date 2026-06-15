from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto('http://127.0.0.1:3000/space/apps', wait_until='networkidle')
    public_text = page.locator('body').inner_text(timeout=5000)
    print('guest_space_forbidden=', '403' in public_text or '没有权限' in public_text or 'Forbidden' in public_text)
    print('guest_text_head=', public_text[:180].replace('\n', '|'))

    page.goto('http://127.0.0.1:3000/auth/login?mode=admin&redirect=/space/apps', wait_until='networkidle')
    page.locator('input').nth(0).fill('admin')
    page.locator('input').nth(1).fill('Admin_123456')
    page.get_by_role('button', name='登录').click()
    page.wait_for_timeout(3500)
    page.wait_for_load_state('networkidle')
    print('admin_url_after_login=', page.url)
    admin_text = page.locator('body').inner_text(timeout=8000)
    print('admin_space_forbidden=', '403' in admin_text or '没有权限' in admin_text or 'Forbidden' in admin_text)
    print('admin_has_config_center=', '配置中心' in admin_text)
    print('admin_has_personal_space=', '个人空间' in admin_text)
    print('admin_text_head=', admin_text[:300].replace('\n', '|'))
    browser.close()
