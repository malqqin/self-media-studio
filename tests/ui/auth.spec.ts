import {test,expect} from '@playwright/test';
import {settings} from './fixtures';
const user={id:'user-test',email:'writer@example.com',display_name:'创作者',role:'user',status:'active',email_verified:true,created_at:'2026-09-26T00:00:00Z',last_login_at:null};

test('email registration waits for verification and logs out',async({page},info)=>{
  let current:any=null;const writes:string[]=[];
  await page.route('**/api/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(req.method()!=='GET')writes.push(path);
    if(path==='/api/auth/status')return route.fulfill({json:{setup_required:false,registration_open:true,mail_ready:true}});
    if(path==='/api/auth/me')return route.fulfill({json:{user:current}});
    if(path==='/api/auth/register')return route.fulfill({json:{message:'验证码已发送'}});
    if(path==='/api/auth/verify'){expect(req.postDataJSON().code).toBe('123456');current=user;return route.fulfill({json:{user}});}
    if(path==='/api/auth/logout'){current=null;return route.fulfill({json:{ok:true}});}
    if(path==='/api/settings')return route.fulfill({json:settings});
    if(path==='/api/tasks'||path==='/api/topics')return route.fulfill({json:[]});
    return route.fulfill({status:500,json:{detail:'unexpected '+path}});
  });
  await page.goto('/');await expect(page.getByRole('heading',{name:'欢迎回到知序'})).toBeVisible();
  await page.screenshot({path:info.outputPath('login-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'邮箱注册',exact:true}).click();
  await page.getByLabel('怎么称呼你').fill('创作者');await page.getByLabel('邮箱',{exact:true}).fill(user.email);await page.getByLabel('密码',{exact:true}).fill('a');
  await page.getByRole('button',{name:'发送验证码',exact:true}).click();await expect(page.getByRole('heading',{name:'验证你的邮箱'})).toBeVisible();
  await expect(page.getByRole('navigation')).toHaveCount(0);
  await page.getByLabel('邮箱验证码').fill('123456');await page.getByRole('button',{name:'验证并进入'}).click();
  await expect(page.getByRole('navigation')).toBeVisible();await expect(page.getByRole('button',{name:'管理中心',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'账号设置'}).click();await page.getByRole('button',{name:'退出登录'}).click();await expect(page.getByRole('heading',{name:'欢迎回到知序'})).toBeVisible();
  expect(writes).toEqual(['/api/auth/register','/api/auth/verify','/api/auth/logout']);
});

test('first boot explains administrator credential and fits mobile',async({page},info)=>{
  await page.route('**/api/auth/status',route=>route.fulfill({json:{setup_required:true,registration_open:true,mail_ready:false}}));
  await page.route('**/api/auth/me',route=>route.fulfill({json:{user:null}}));
  await page.setViewportSize({width:390,height:844});await page.goto('/');
  await expect(page.getByRole('heading',{name:'设置管理员账号'})).toBeVisible();await expect(page.getByText(/data\/admin-setup.txt/)).toBeVisible();
  await expect(page.getByLabel('初始化凭证')).toHaveAttribute('type','password');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:info.outputPath('setup-mobile.png'),fullPage:true});
});

test('administrator users and centered SMTP configuration',async({page},info)=>{
  const admin={...user,id:'admin-test',display_name:'管理员',role:'admin'};let mail:any={ready:false,password_configured:false};
  await page.route('**/api/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(path==='/api/auth/me')return route.fulfill({json:{user:admin}});
    if(path==='/api/auth/status')return route.fulfill({json:{setup_required:false,registration_open:true,mail_ready:false}});
    if(path==='/api/admin/users')return route.fulfill({json:{items:[admin,user],page:1,total:2}});
    if(path==='/api/admin/settings')return route.fulfill({json:{registration_open:true,smtp:mail}});
    if(path==='/api/admin/events'||path==='/api/tasks'||path==='/api/topics')return route.fulfill({json:[]});
    if(path==='/api/settings')return route.fulfill({json:settings});
    if(path==='/api/admin/smtp'){const {password,...saved}=req.postDataJSON();expect(password).toBe('test-auth-code');mail={...saved,ready:true,password_configured:true};return route.fulfill({json:mail});}
    return route.fulfill({status:500,json:{detail:'unexpected '+path}});
  });
  await page.goto('/#admin');await expect(page.getByRole('heading',{name:'管理中心'})).toBeVisible();
  await page.screenshot({path:info.outputPath('admin-users.png'),fullPage:true});
  await page.getByRole('button',{name:'平台设置',exact:true}).click();const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
  await page.getByLabel('SMTP 地址').fill('smtp.example.com');await page.getByLabel('SMTP 账号').fill('owner@example.com');await page.getByLabel('密码 / 邮箱授权码').fill('test-auth-code');await page.getByLabel('发件邮箱').fill('owner@example.com');
  await page.getByRole('button',{name:'保存邮件配置'}).click();await expect(page.getByLabel('密码 / 邮箱授权码')).toBeEmpty();
  await expect(page.getByRole('button',{name:'发送测试邮件给我'})).toBeEnabled();
  await page.screenshot({path:info.outputPath('smtp-settings.png'),fullPage:true});
});

test('administrator setup explains short credential and imports complete file',async({page})=>{
  const requests:any[]=[];const credential='test-setup-credential-'.padEnd(48,'x');
  await page.route('**/api/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(path==='/api/auth/status')return route.fulfill({json:{setup_required:true,registration_open:true,mail_ready:false}});
    if(path==='/api/auth/me')return route.fulfill({json:{user:null}});
    if(path==='/api/auth/setup'){requests.push(req.postDataJSON());return route.fulfill({json:{user}});}
    if(path==='/api/settings')return route.fulfill({json:settings});
    return route.fulfill({json:[]});
  });
  await page.goto('/');
  await page.getByLabel('初始化凭证',{exact:true}).fill('my-password');
  await page.getByLabel('怎么称呼你').fill('管理员');await page.getByLabel('邮箱',{exact:true}).fill(user.email);
  await page.getByLabel('密码',{exact:true}).fill('a');
  await page.getByRole('button',{name:'创建管理员并进入'}).click();
  await expect(page.getByRole('alert')).toContainText('初始化凭证不完整');
  await expect(page.locator('#setup-token-error')).toContainText('这里不是登录密码');
  await expect(page.getByLabel('初始化凭证',{exact:true})).toBeFocused();
  expect(requests).toHaveLength(0);
  const chooser=page.waitForEvent('filechooser');await page.getByRole('button',{name:'从凭证文件导入'}).click();
  await (await chooser).setFiles({name:'admin-setup.txt',mimeType:'text/plain',buffer:Buffer.from('\ufeff'+credential+'\r\n')});
  await expect(page.getByLabel('初始化凭证',{exact:true})).toHaveValue(credential);
  await expect(page.locator('#setup-token-error')).toHaveCount(0);
  await expect(page.getByLabel('密码',{exact:true})).toHaveValue('a');
  await page.getByRole('button',{name:'创建管理员并进入'}).click();
  await expect(page.getByRole('navigation')).toBeVisible();
  expect(requests).toHaveLength(1);expect(requests[0].setup_token).toBe(credential);
});
