// Serves the REAL templates/index.html; mocks only the backend (Gemini / Swiggy MCP aren't callable offline).
const http=require('http'),fs=require('fs'),path=require('path');
const HTML=fs.readFileSync('C:/Projects/fridge-to-fork/templates/index.html','utf8');
const sse=(res,o)=>res.write('data: '+JSON.stringify(o)+'\n\n');
const later=(ms,fn)=>setTimeout(fn,ms);
const ING=[["Eggs","6",96],["Bell Peppers","2",88],["Cheese Slices","1 pack",86],["Lettuce","1 head",91],["Green Beans","1 bunch",83],["Lemons","3",79],["Green Olives","1 jar",84],["Mustard","1 jar",90]];
const RI=[
 ["Eggs","3",30,true,false,"dairy"],["Cheese Slices","2",20,true,false,"dairy"],["Bell Peppers","1 small",15,true,false,"vegetables"],
 ["Onion","1 medium",6,false,true,"vegetables"],["Turmeric Powder","1/4 tsp",2,false,true,"spices"],["Salt","to taste",1,false,true,"spices"],["Oil","1 tbsp",4,false,true,"pantry"],
 ["Green Chillies","2",5,false,false,"vegetables"],["Coriander Leaves","1 bunch",10,false,false,"vegetables"],["Bread Slices","4",25,false,false,"bakery"]];
const MISS=["Green Chillies","Coriander Leaves","Bread Slices"];
const STEPS=["Finely chop the onion, green chillies, coriander and bell pepper.","Whisk the eggs with salt and turmeric, then stir in the chopped vegetables.","Heat oil in a pan and pour in the egg mixture.","Lay cheese slices on one half, cook until set and fold over.","Toast the bread and serve the omelette hot."];
http.createServer((req,res)=>{
  const u=new URL(req.url,'http://x');
  const file=p=>{res.writeHead(200,{'Content-Type':p.endsWith('.jpg')?'image/jpeg':'application/octet-stream'});res.end(fs.readFileSync(p))};
  if(u.pathname==='/')return(res.writeHead(200,{'Content-Type':'text/html'}),res.end(HTML));
  if(u.pathname==='/dish.jpg')return file(path.join(__dirname,'dish.jpg'));
  if(u.pathname==='/auth/status')return(res.writeHead(200,{'Content-Type':'application/json'}),res.end('{"authenticated":true}'));
  if(u.pathname==='/api/dish-image'){res.writeHead(200,{'Content-Type':'application/json'});return res.end(fs.existsSync(path.join(__dirname,'dish.jpg'))?'{"image_url":"/dish.jpg","found":true}':'{"image_url":"","found":false}')}
  if(u.pathname==='/api/ingredient-image'){res.writeHead(200,{'Content-Type':'application/json'});return res.end('{"image_url":"","found":false}')}
  if(u.pathname==='/api/youtube'){res.writeHead(200,{'Content-Type':'application/json'});return res.end('{"videos":[],"first_thumbnail":""}')}
  if(u.pathname==='/api/dish-suggestions'){res.writeHead(200,{'Content-Type':'application/json'});return res.end('{"suggestions":[]}')}
  if(u.pathname==='/api/scan'){
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});
    sse(res,{type:'progress',step:1,message:'Scanning your fridge with AI vision…'});
    later(4200,()=>sse(res,{type:'step1',raw_description:'A well-stocked fridge.',ingredients:ING.map(([name,quantity,confidence])=>({name,quantity,confidence}))}));
    later(4400,()=>sse(res,{type:'progress',step:2,message:'Planning your meals…'}));
    later(6800,()=>{sse(res,{type:'step2',decision:'order_groceries',recommended_meal:'Masala Cheese Omelette',reasoning:'You have eggs, cheese and bell peppers — only a few fresh items are missing.',
      suggestions:[
        {name:'Masala Cheese Omelette',description:'Fluffy eggs folded over melted cheese with peppers, green chillies and coriander.',cuisine:'Indian',can_cook_now:false,missing_ingredients:MISS,prep_time_minutes:15},
        {name:'Egg Fried Rice',description:'Quick wok-tossed rice with scrambled eggs and green beans.',cuisine:'Indo-Chinese',can_cook_now:true,missing_ingredients:[],prep_time_minutes:20},
        {name:'Cheese Pepper Toast',description:'Crisp toast piled with cheese and sautéed bell peppers.',cuisine:'Continental',can_cook_now:false,missing_ingredients:['Bread Slices'],prep_time_minutes:10}],
      recipe_ingredients:RI.map(([name,quantity,p,f,s,c])=>({name,quantity,estimated_price_inr:p,found_in_fridge:f,is_staple:s,category:c})),
      cooking_steps:STEPS,matched_fridge_items:['Eggs','Cheese Slices','Bell Peppers']});
      sse(res,{type:'awaiting_user_choice',reasoning:'You have eggs, cheese and bell peppers — only a few fresh items are missing.',recommended_meal:'Masala Cheese Omelette',missing_ingredients:MISS,total_order_price_inr:40});
      sse(res,{type:'top_up',suggestions:[{name:'Butter',estimated_price:58},{name:'Pav',estimated_price:30},{name:'Tomato Ketchup',estimated_price:70}]});
      sse(res,{type:'complete'});res.end()});
    return;
  }
  if(u.pathname==='/api/order'){
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache'});
    sse(res,{type:'progress',step:3,message:'Routing your order…'});
    later(2600,()=>{sse(res,{type:'step3',decision:'order_groceries',placed:true,order_id:'#IM-48213907',platform:'Instamart',items:MISS,eta_minutes:12});sse(res,{type:'complete'});res.end()});
    return;
  }
  res.writeHead(404);res.end();
}).listen(8765,()=>console.log('up'));
