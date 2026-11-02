// 실제 주문 화면 JS, 합성 API. 운영 계정이나 주문은 사용하지 않는다.
const result = document.createElement('pre'); result.id = 'broker-nav-result'; document.body.append(result);
const checks = [];
const check = (name, ok) => { if (!ok) throw Error(name); checks.push(name); };
const tick = () => new Promise(resolve => setTimeout(resolve, 50));
const rows = [
  {id:'00000000-0000-4000-8000-000000000001',owner:'me',broker:'kis-direct',environment:'paper',order_type:'LIMIT',side:'SELL',quantity:3,filled_quantity:1,status:'PARTIALLY_FILLED',price:70000},
  {id:'00000000-0000-4000-8000-000000000002',owner:'me',broker:'kis-direct',environment:'paper',order_type:'LIMIT',side:'SELL',quantity:3,filled_quantity:1,status:'CANCELLED',price:70000},
  {id:'other',owner:'batch',broker:'kis-direct',environment:'paper',order_type:'LIMIT',side:'SELL',quantity:3,filled_quantity:1,status:'CANCELLED'},
  {id:'real',owner:'me',broker:'kis-direct',environment:'real',order_type:'LIMIT',side:'SELL',quantity:3,filled_quantity:1,status:'CANCELLED'},
];
let allow = false, release, posts = [];
window.confirm = () => allow;
window.alert = () => {};
window.fetch = async (input, options={}) => {
  const path = String(input);
  if (options.method === 'POST') {
    posts.push(path);
    await new Promise(resolve => {release = resolve;});
    return new Response(JSON.stringify({status:'ACCEPTED'}),{status:200});
  }
  return new Response(JSON.stringify(path.startsWith('/api/quant/live-orders') ? {orders:rows} : {}),{status:200});
};
try {
  await import('/js/settings.js');
  document.getElementById('live-orders-refresh').click(); await tick();
  check('본인 모의 주문만 취소·재주문 버튼 표시',document.querySelectorAll('button[data-kis-action]').length===2);
  const cancel = document.querySelector('[data-kis-action="cancel"]');
  cancel.click(); await tick();
  check('취소 확인창 거부 시 전송 없음', posts.length===0);
  allow = true; cancel.click(); cancel.click(); await tick();
  check('취소 연속 클릭도 한 번 전송', posts.length===1 && posts[0].endsWith('/'+rows[0].id+'/cancel'));
  check('응답 대기 중 버튼 비활성',cancel.disabled);
  release(); await tick();
  const retry = document.querySelector('[data-kis-action="retry"]');
  retry.click(); await tick();
  check('선택한 원 주문으로 재주문 요청',posts.length===2 && posts[1].endsWith('/'+rows[1].id+'/retry'));
  release(); await tick();
  check('재주문 후 주문 목록 다시 표시',document.querySelectorAll('button[data-kis-action]').length===2);
  check('자동매매·위험 설정 저장 없음',posts.every(path=>path.startsWith('/api/quant/kis/orders/')));
  result.textContent = JSON.stringify({ok:true,checks});
} catch(error) {result.textContent = JSON.stringify({ok:false,checks,error:String(error),stack:error.stack});}
