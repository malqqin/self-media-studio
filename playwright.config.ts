import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./tests/ui',fullyParallel:false,workers:1,timeout:30000,
  use:{baseURL:'http://127.0.0.1:8765',headless:true,viewport:{width:1280,height:1000},
    launchOptions:{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'},
    screenshot:'only-on-failure',trace:'retain-on-failure'},
});
