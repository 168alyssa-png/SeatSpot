const menu = [
  {id:'original',name:'Original Cookie',price:45,cls:'original'},
  {id:'choc',name:'Chocolate Cookie',price:45,cls:''},
  {id:'matcha',name:'Matcha Cookie',price:45,cls:'matcha'},
  {id:'red',name:'Red Velvet Cookie',price:49,cls:'redv'}
];
const visitor = {name:null,ready:false,pending:false,entered:false};
const cookieState = {inventory:[],selected:null,loading:true,error:null,pending:false,refreshing:false,version:0,timer:null,collected:null};
try { cookieState.collected=sessionStorage.getItem('seatspot.collectedOrder'); } catch {}

function renderMenu(){
  const escape=SeatSpotAPI.escape;
  const ordered=Boolean(state.activeOrder);
  const menuBox=document.getElementById('menu');
  menuBox.innerHTML=menu.map(cookie=>{
    const stock=cookieState.inventory.find(item=>item.id===cookie.id);
    const available=stock?.active && stock.quantity_remaining>0;
    const disabled=!visitor.name || ordered || cookieState.pending || cookieState.loading || Boolean(cookieState.error) || !available;
    const label=!stock?'Stock unavailable':stock.quantity_remaining===0?'Sold out':!stock.active?'Unavailable':cookieState.selected===cookie.id?'Selected':'Select';
    const quantity=stock?`${stock.quantity_remaining} remaining`:'Checking stock…';
    return `<div class="item" data-cookie="${cookie.id}">
      <div class="cookie ${cookie.cls}" aria-hidden="true"></div>
      <div><b>${cookie.name}</b><div class="small">Freshly baked • pickup when ready</div>
        <div class="price">${cookie.price} THB</div><div class="stock-remaining" data-stock="${cookie.id}">${escape(quantity)}</div></div>
      <button class="btn ${cookieState.selected===cookie.id?'':'secondary'} cookie-select" aria-label="${escape(label)} ${cookie.name}"
        aria-pressed="${cookieState.selected===cookie.id}" ${disabled?'disabled':''} onclick="selectCookie('${cookie.id}')">${label}</button>
    </div>`;
  }).join('');
  const status=document.getElementById('inventoryStatus');
  status.textContent=cookieState.error?'Stock updates are unavailable. Ordering is paused until reconnected.':cookieState.loading?'Checking current stock…':'Stock is shared and refreshes automatically every 3 seconds.';
  document.getElementById('retryInventory').hidden=!cookieState.error;
  const summary=document.getElementById('cartSummary');
  const action=document.getElementById('cartAction');
  if(state.activeOrder){
    const order=state.activeOrder;
    const collected=cookieState.collected===order.id;
    summary.innerHTML=`<b>${escape(order.cookie_flavor)} — ${collected?'Collected ✓':escape(order.status)}</b>
      <div class="small">${escape(order.customer_name || visitor.name || 'Guest')}${order.table_id?` • Table ${escape(order.table_id)}`:''}</div>
      <div class="small">One cookie ordered for this session</div>`;
    action.textContent=order.status==='Ready'&&!collected?'Confirm pickup':collected?'Collected ✓':'Order placed ✓';
    action.disabled=order.status!=='Ready'||collected;
  }else{
    const selected=menu.find(item=>item.id===cookieState.selected);
    summary.innerHTML=selected?`<b>${escape(selected.name)}</b><div class="small">1 cookie • ${selected.price} THB</div>`:'<b>Select one cookie</b><div class="small">One cookie per session</div>';
    action.textContent=cookieState.pending?'Placing order…':'Place order';
    action.disabled=!visitor.name||!selected||cookieState.pending||cookieState.loading||Boolean(cookieState.error);
  }
  action.style.opacity=action.disabled?'.65':'1';
  action.style.cursor=action.disabled?'not-allowed':'pointer';
  setStep(state.activeOrder?({New:1,Preparing:2,Ready:3}[state.activeOrder.status]||0):0);
}

function selectCookie(id){
  const stock=cookieState.inventory.find(item=>item.id===id);
  if(!visitor.name||state.activeOrder||cookieState.pending||cookieState.error||!stock?.active||stock.quantity_remaining<=0) return;
  cookieState.selected=id;
  renderMenu();
}

function applyCookieSnapshot(snapshot){
  applyVisitorSession(snapshot);
  const previous=state.activeOrder?.status;
  cookieState.inventory=snapshot.inventory;
  cookieState.loading=false;cookieState.error=null;
  state.activeOrder=snapshot.order;
  state.orderPlaced=Boolean(snapshot.order);
  state.orderStatus=snapshot.order?({New:'ordered',Preparing:'preparing',Ready:'ready'}[snapshot.order.status]||'idle'):'idle';
  const selected=cookieState.inventory.find(item=>item.id===cookieState.selected);
  if(snapshot.order||!selected?.active||selected.quantity_remaining<=0) cookieState.selected=null;
  renderMenu();
  if(previous && snapshot.order && previous!==snapshot.order.status){
    toast(snapshot.order.status==='Ready'?'Ready for pickup! 🍪':`Your order is ${snapshot.order.status.toLowerCase()}`);
  }
}

async function refreshCustomerOrders(){
  if(cookieState.refreshing||visitor.pending) return;
  cookieState.refreshing=true;
  const version=cookieState.version;
  try{
    const snapshot=await SeatSpotAPI.request('state');
    if(version===cookieState.version) applyCookieSnapshot(snapshot);
  }catch(error){
    if(version===cookieState.version){cookieState.loading=false;cookieState.error=error.message;
      if(!visitor.entered){document.getElementById('welcomeMessage').textContent='Could not connect. Please retry to save your name.';document.getElementById('welcomeRetry').hidden=false}
      renderMenu()}
  }finally{cookieState.refreshing=false}
}

async function placeOrder(){
  if(state.activeOrder){
    if(state.activeOrder.status==='Ready'){
      cookieState.collected=state.activeOrder.id;
      try{sessionStorage.setItem('seatspot.collectedOrder',cookieState.collected)}catch{}
      renderMenu();toast('Order collected. Your one-cookie session limit is still in place.');
    }
    return;
  }
  if(!visitor.name||!cookieState.selected||cookieState.pending||cookieState.loading||cookieState.error) return;
  cookieState.pending=true;cookieState.version++;
  const selected=cookieState.selected;
  renderMenu();
  try{
    const snapshot=await SeatSpotAPI.request('order',{catalog_version:'four-flavors-v1',cookie_id:selected,quantity:1,table_id:state.claimed||null});
    applyCookieSnapshot(snapshot);
    toast(`${snapshot.already_ordered?'Already ordered':'Order placed'}: ${snapshot.order.cookie_flavor}`);
  }catch(error){
    toast(error.message);
    // Resolve an uncertain network result from the server before offering retry.
    cookieState.error=error.message;
    await refreshCustomerOrders();
  }finally{
    cookieState.pending=false;
    renderMenu();
  }
}

// Table changes and Reset do not create a new ordering identity or erase the
// server's order. Only the unsubmitted selection is cleared.
function resetOrderSession(){cookieState.selected=null;renderMenu()}

function applyVisitorSession(snapshot){
  if(visitor.pending) return;
  visitor.ready=true;
  visitor.name=snapshot.customer_name || null;
  try{
    if(visitor.name) sessionStorage.setItem('seatspot.visitorName',JSON.stringify({customer_name:visitor.name,session_expires_at:snapshot.session_expires_at}));
    else sessionStorage.removeItem('seatspot.visitorName');
  }catch{}
  const app=document.getElementById('seatspotApp');
  document.getElementById('welcomeScreen').hidden=Boolean(visitor.name);
  app.hidden=!visitor.name;app.inert=!visitor.name;
  document.getElementById('welcomeContinue').disabled=false;
  document.getElementById('welcomeRetry').hidden=true;
  if(visitor.name){
    if(!visitor.entered){visitor.entered=true;recognizeTableLink()}
  }else{
    if(visitor.entered){closeModal();visitor.entered=false}
    document.getElementById('welcomeMessage').textContent='Use up to 30 characters. Saved for this SeatSpot session.';
  }
}

async function submitVisitorName(event){
  event.preventDefault();
  if(visitor.pending||!visitor.ready) return;
  const name=document.getElementById('customerName').value.trim();
  const message=document.getElementById('welcomeMessage');
  if(!name||name.length>30||/[\u0000-\u001f\u007f]/u.test(name)){
    message.textContent='Enter a name between 1 and 30 characters.';return;
  }
  visitor.pending=true;cookieState.version++;
  document.getElementById('welcomeContinue').disabled=true;
  message.textContent='Saving your name…';
  try{
    const session=await SeatSpotAPI.request('welcome',{customer_name:name});
    visitor.pending=false;applyVisitorSession(session);renderMenu();
  }catch(error){message.textContent=error.message;document.getElementById('welcomeRetry').hidden=false}
  finally{visitor.pending=false;document.getElementById('welcomeContinue').disabled=!visitor.ready}
}

document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('welcomeForm').addEventListener('submit',submitVisitorName);
  try{
    const cached=JSON.parse(sessionStorage.getItem('seatspot.visitorName'));
    if(typeof cached?.customer_name==='string'&&cached.customer_name.trim()&&cached.customer_name.length<=30&&new Date(cached.session_expires_at).getTime()>Date.now()) applyVisitorSession(cached);
  }catch{}
  refreshCustomerOrders();
  cookieState.timer=setInterval(()=>{if(!document.hidden) refreshCustomerOrders()},3000);
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden) refreshCustomerOrders()});
window.addEventListener('pageshow',()=>refreshCustomerOrders());
