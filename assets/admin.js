(() => {
  const api=SeatSpotAPI;
  const message=document.getElementById('staffMessage');
  const login=document.getElementById('staffLogin');
  const dashboard=document.getElementById('staffDashboard');
  let refreshing=false,busy=false,authenticated=false,generation=0;
  const stockForms=new Map();
  function showLogin(text='Sign in to manage stock and orders.'){
    authenticated=false;dashboard.hidden=true;login.hidden=false;
    message.textContent=text;
    document.getElementById('staffOrders').replaceChildren();
    document.getElementById('staffInventory').replaceChildren();
    stockForms.clear();
  }
  function renderInventory(items){
    const root=document.getElementById('staffInventory');
    for(const item of items){
      let form=stockForms.get(item.id);
      if(!form){
        form=document.createElement('form');form.className='card stock-form';form.dataset.cookie=item.id;
        form.innerHTML=`<h3></h3><div class="available stock-count"></div><p class="small stock-status"></p>
          <label>Set quantity<input name="quantity" type="number" min="0" max="1000000" step="1" required></label>
          <label class="active-toggle"><input name="active" type="checkbox"> Active for customers</label>
          <div class="row stock-buttons"><button class="btn" type="submit">Set stock</button>
            <button class="btn secondary" type="button" data-adjust="-1">−1</button>
            <button class="btn secondary" type="button" data-adjust="1">+1</button></div>`;
        form.querySelector('h3').textContent=item.flavor;
        form.addEventListener('input',()=>{form.dataset.dirty='true'});
        form.addEventListener('change',()=>{form.dataset.dirty='true'});
        form.addEventListener('submit',event=>{
          event.preventDefault();
          const quantity=Number(form.elements.quantity.value);
          if(!Number.isInteger(quantity)||quantity<0||quantity>1000000){message.textContent='Enter a whole quantity between 0 and 1,000,000.';return}
          mutate('inventory',{cookie_id:item.id,quantity,active:form.elements.active.checked},()=>{form.dataset.dirty='false'});
        });
        form.querySelectorAll('[data-adjust]').forEach(button=>button.addEventListener('click',()=>{
          mutate('inventory',{cookie_id:item.id,adjustment:Number(button.dataset.adjust)},()=>{form.dataset.dirty='false'});
        }));
        root.append(form);stockForms.set(item.id,form);
      }
      form.querySelector('.stock-count').textContent=`${item.quantity_remaining} remaining`;
      form.querySelector('.stock-status').textContent=item.quantity_remaining===0?'Sold out':item.active?'Active':'Paused for customers';
      if(form.dataset.dirty!=='true'){
        form.elements.quantity.value=item.quantity_remaining;
        form.elements.active.checked=item.active;
      }
    }
  }
  function renderOrders(orders){
    const root=document.getElementById('staffOrders');
    const fragment=document.createDocumentFragment();
    for(const order of orders){
      const row=document.createElement('tr');row.dataset.order=order.id;
      for(const value of [order.id,order.table_id||'No table',order.cookie_flavor,String(order.quantity),new Date(order.created_at).toLocaleString()]){
        const cell=document.createElement('td');cell.textContent=value;row.append(cell);
      }
      const actions=document.createElement('td');
      const label=document.createElement('b');label.className='badge order-status';label.textContent=order.status;actions.append(label);
      const buttons=document.createElement('div');buttons.className='status-buttons';
      for(const status of ['New','Preparing','Ready']){
        const button=document.createElement('button');button.type='button';button.className='btn secondary';button.textContent=status;
        button.disabled=busy||status===order.status;button.setAttribute('aria-label',`Mark order ${order.id} ${status}`);
        button.addEventListener('click',()=>mutate('order-status',{order_id:order.id,status}));buttons.append(button);
      }
      actions.append(buttons);row.append(actions);fragment.append(row);
    }
    root.replaceChildren(fragment);
    document.getElementById('noStaffOrders').hidden=orders.length>0;
  }
  async function refresh(force=false){
    if(refreshing||busy&&!force) return;
    refreshing=true;const version=generation;
    try{
      const snapshot=await api.request('staff-state');
      if(version!==generation) return;
      authenticated=true;login.hidden=true;dashboard.hidden=false;
      document.getElementById('staffIdentity').textContent=snapshot.staff.email;
      renderInventory(snapshot.inventory);renderOrders(snapshot.orders);
      message.textContent=`Updated ${new Date().toLocaleTimeString()}`;
    }catch(error){
      if(version!==generation) return;
      if(error.status===401||error.status===403) showLogin(error.message);
      else{message.textContent=error.message;if(!authenticated){login.hidden=false;dashboard.hidden=true}}
    }finally{refreshing=false}
  }
  async function mutate(action,body,onSuccess){
    if(busy) return;
    busy=true;generation++;
    dashboard.querySelectorAll('button').forEach(button=>button.disabled=true);
    try{
      await api.request(action,body);onSuccess?.();
      // An older in-flight poll is ignored by the generation guard.
      while(refreshing) await new Promise(resolve=>setTimeout(resolve,25));
      await refresh(true);
    }catch(error){
      if(error.status===401||error.status===403) showLogin(error.message);
      else message.textContent=error.message;
    }finally{
      busy=false;
      dashboard.querySelectorAll('.stock-form button,#staffLogout,#staffRefresh').forEach(button=>button.disabled=false);
      if(authenticated) refresh();
    }
  }
  document.getElementById('loginForm').addEventListener('submit',async event=>{
    event.preventDefault();const button=document.getElementById('staffLoginButton');button.disabled=true;generation++;
    try{
      await api.request('staff-login',{email:document.getElementById('staffEmail').value,password:document.getElementById('staffPassword').value});
      document.getElementById('staffPassword').value='';
      while(refreshing) await new Promise(resolve=>setTimeout(resolve,25));
      await refresh();
    }catch(error){message.textContent=error.message;document.getElementById('staffPassword').value=''}
    finally{button.disabled=false}
  });
  document.getElementById('staffLogout').addEventListener('click',async()=>{
    if(busy) return;
    generation++;
    try{await api.request('staff-logout',{});showLogin()}
    catch(error){message.textContent=error.message}
  });
  document.getElementById('staffRefresh').addEventListener('click',()=>refresh());
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&authenticated) refresh()});
  setInterval(()=>{if(!document.hidden&&authenticated) refresh()},3000);
  refresh();
})();
