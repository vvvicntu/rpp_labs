from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter
from app import db
from app.schema import schema, get_context
# жизненный цикл приложения
@asynccontextmanager
async def lifespan(app):
    await db.create_tables() # запуск - создание табл
    try: yield # работа
    finally: await db.engine.dispose() # смерть (освобождение ресурсов и пула)
        
# создание приложения
app = FastAPI(title='ЛР 6 - доставка еды', lifespan=lifespan)
# подсчет скл-запросов 
@app.middleware('http')
async def sql_counter(request: Request, call_next):
    trace = []
    token = db.sql_trace.set(trace) # помещаем список в эту переменную контекста
    try:
        response = await call_next(request # передача запроса на обработку
        response.headers['X-SQL-Count'] = str(len(trace)) # подсчет длины трэйса
        if request.url.path == '/graphql' and request.method == 'POST':
            print(f'SQL COUNT: {len(trace)}', flush=True)
        return response
    finally: db.sql_trace.reset(token)

@app.get('/health')
async def health(): return {'status':'ok'}
app.include_router(GraphQLRouter(schema, context_getter=get_context, graphql_ide='graphiql'), prefix='/graphql')
