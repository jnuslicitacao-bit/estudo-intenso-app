import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth

# 🌟 SÓ CARREGA O .ENV SE ESTIVER LOCALMENTE (Impede o bug de apagar as variáveis no Render)
if not os.environ.get("RENDER"):
    print("💻 Carregando variáveis do arquivo .env local...")
    load_dotenv()

app = Flask(__name__)
# É altamente recomendável ter uma secret key definida para sessões estáveis do OAuth
app.secret_key = os.getenv("FLASK_SECRET_KEY", "uma_chave_secreta_muito_segura_123")
CORS(app)

# Busca a chave de API da OpenAI de forma segura no sistema operacional
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Configuração do OAuth do Google unificada no escopo inicial do app
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID", "SEU_CLIENT_ID_AQUI"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "SUA_CHAVE_SECRETA_AQUI"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)


def get_db_connection():
    """Conecta ao banco PostgreSQL usando a URL de Ambiente do Render ou Localhost"""
    database_url = os.environ.get("DATABASE_URL")
    
    if not database_url:
        database_url = "postgresql://administrador:L1fnSYJTUY8fxCNuHrWA7IiFieD814Wr@dpg-d8iprv6q1p3s73f0qk5g-a.ohio-postgres.render.com/estudo_intenso_db"
    
    if database_url and "localhost" not in database_url:
        print("🚀 [DATABASE] Conectando ao Postgres do Render com Psycopg2...")
        return psycopg2.connect(database_url.strip())
    else:
        print("💻 [DATABASE] Nenhuma URL de nuvem ativa. Conectando ao Postgres Local...")
        return psycopg2.connect(
            user="administrador",
            password="nova_senha123",
            host="localhost",
            port=5432,
            database="estudo_intensivo_db"
        )


def inicializar_banco():
    """Garante as tabelas na nuvem com SQL correto para PostgreSQL"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Tabela de controle
        cur.execute("""
            CREATE TABLE IF NOT EXISTS controle_atualizacao (
                id SERIAL PRIMARY KEY,
                ultima_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # 2. Tabela de simulados
        cur.execute("""
            CREATE TABLE IF NOT EXISTS simulados (
                id SERIAL PRIMARY KEY,
                usuario_id INT,
                materia VARCHAR(100),
                nota INT,
                data_realizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ [BANCO] Tabelas criadas/validadas com sucesso na Nuvem!")
    except Exception as e:
        print(f"❌ [ERRO CRÍTICO CRIAÇÃO TABELAS]: {str(e)}")

# Executa a inicialização automática das tabelas essenciais
inicializar_banco()


# ==========================================
# ROTAS DE AUTENTICAÇÃO (LOGIN E CADASTRO)
# ==========================================

@app.route('/api/cadastro', methods=['POST'])
def cadastrar_usuario():
    """Garante a criação da tabela de usuários no banco de dados e registra uma nova conta"""
    try:
        dados = request.get_json()
        if not dados:
            print("❌ ERRO NO CADASTRO: Nenhum dado JSON foi recebido.")
            return jsonify({"status": "erro", "mensagem": "Requisição inválida. Envie dados em formato JSON."}), 400
            
        nome = dados.get('nome')
        email = dados.get('email')
        senha = dados.get('senha')

        print(f"📥 Tentativa de cadastro recebida - Nome: {nome}, Email: {email}, Tem Senha: {bool(senha)}")

        if not nome or not email or not senha:
            return jsonify({"status": "erro", "mensagem": "Por favor, preencha todos os campos obrigatórios."}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Garante que a tabela exista com a estrutura esperada
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL UNIQUE,
                senha VARCHAR(255) NOT NULL,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # 2. Verifica se o e-mail já não está cadastrado na nuvem
        cur.execute("SELECT id FROM usuarios WHERE email = %s;", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"status": "erro", "mensagem": "Este e-mail já está sendo utilizado por outro estudante."}), 400

        # 3. Cria o hash de segurança para a senha e insere no banco
        senha_criptografada = generate_password_hash(senha)
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s);",
            (nome, email, senha_criptografada)
        )
        conn.commit()
        
        cur.close()
        conn.close()
        print(f"🎉 Usuário {nome} cadastrado com sucesso na Nuvem!")
        return jsonify({"status": "sucesso", "mensagem": "Conta criada com sucesso!"}), 201

    except Exception as e:
        print(f"❌ ERRO CRÍTICO NO CADASTRO: {str(e)}")
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {str(e)}"}), 500


@app.route('/api/login', methods=['POST'])
def login_usuario():
    """Valida as credenciais do usuário comparando o e-mail e o hash da senha"""
    try:
        dados = request.get_json()
        email = dados.get('email')
        senha = dados.get('senha')

        if not email or not senha:
            return jsonify({"status": "erro", "mensagem": "Preencha e-mail e senha."}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT id, nome, senha FROM usuarios WHERE email = %s;", (email,))
        usuario_encontrado = cur.fetchone()
        
        cur.close()
        conn.close()

        if not usuario_encontrado:
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha incorretos."}), 401

        if check_password_hash(usuario_encontrado[2], senha):
            return jsonify({
                "status": "sucesso",
                "usuario": {
                    "id": usuario_encontrado[0],
                    "nome": usuario_encontrado[1]
                }
            }), 200
        else:
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha incorretos."}), 401

    except Exception as e:
        print(f"❌ ERRO CRÍTICO NO LOGIN: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# ==========================================
# ROTAS DO SISTEMA DE SIMULADOS E REDAÇÃO
# ==========================================

@app.route('/api/questoes', methods=['GET'])
def obter_questoes():
    """Busca questões no banco de dados, permitindo filtrar por matéria de forma opcional"""
    materia_filtrada = request.args.get('materia') 
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if materia_filtrada:
            cur.execute(
                "SELECT id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e FROM questoes WHERE LOWER(materia) = LOWER(%s) LIMIT 10;",
                (materia_filtrada,)
            )
        else:
            cur.execute("SELECT id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e FROM questoes LIMIT 10;")
            
        questoes = cur.fetchall()
        cur.close()
        conn.close()
        
        lista_questoes = []
        for q in questoes:
            lista_questoes.append({
                "id": q[0], 
                "materia": q[1], 
                "enunciado": q[2],
                "opcoes": {"A": q[3], "B": q[4], "C": q[5], "D": q[6], "E": q[7]}
            })
        return jsonify(lista_questoes), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/simulado/salvar', methods=['POST'])
def salvar_simulado():
    """Garante a criação da tabela de histórico e salva o desempenho do aluno na nuvem"""
    try:
        dados = request.get_json()
        usuario_id = dados.get('usuario_id')
        materia = dados.get('materia', 'Geral')
        nota = dados.get('nota', 0)

        if not usuario_id:
            return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS simulados_realizados (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                materia VARCHAR(100) NOT NULL,
                nota INTEGER NOT NULL,
                data_realizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        cur.execute(
            """INSERT INTO simulados_realizados (usuario_id, materia, nota) 
               VALUES (%s, %s, %s);""",
            (usuario_id, materia, nota)
        )
        conn.commit()
        
        cur.close()
        conn.close()
        print(f"📊 Nota {nota}% em {materia} salva com sucesso na nuvem!")
        return jsonify({"status": "sucesso", "mensagem": "Resultado salvo com sucesso!"}), 201

    except Exception as e:
        print(f"❌ ERRO AO SALVAR SIMULADO: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/simulados/historico', methods=['GET'])
def obter_historico_simulados():
    """Busca os últimos desempenhos salvos na nuvem para o usuário especificado"""
    try:
        usuario_id = request.args.get('usuario_id')
        if not usuario_id:
            return jsonify({"status": "erro", "mensagem": "ID do usuário é obrigatório."}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS simulados_realizados (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER NOT NULL,
                materia VARCHAR(100) NOT NULL,
                nota INTEGER NOT NULL,
                data_realizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        cur.execute("""
            SELECT materia, nota 
            FROM simulados_realizados 
            WHERE usuario_id = %s 
            ORDER BY data_realizacao DESC 
            LIMIT 4;
        """, (usuario_id,))
        
        resultados = cur.fetchall()
        cur.close()
        conn.close()

        historico = []
        for r in resultados:
            historico.append({
                "materia": r[0],
                "nota": r[1]
            })

        return jsonify(historico), 200

    except Exception as e:
        print(f"❌ ERRO AO BUSCAR HISTÓRICO: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/desempenho', methods=['GET'])
def obter_desempenho():
    """Busca métricas históricas filtrando pelo ID dinâmico do usuário logado"""
    usuario_id = request.args.get('usuario_id')
    
    if not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT tema, nota_final, texto, feedback_ia FROM redacoes WHERE usuario_id = %s ORDER BY data_envio DESC LIMIT 5;", (usuario_id,))
        redacoes_banco = cur.fetchall()
        
        cur.execute("SELECT AVG(nota) FROM simulados_realizados WHERE usuario_id = %s;", (usuario_id,))
        media_simulado = cur.fetchone()[0]
        media_simulado = int(media_simulado) if media_simulado else 0 

        cur.close()
        conn.close()
        
        historico_redacoes = []
        for r in redacoes_banco:
            historico_redacoes.append({
                "tema": r[0],
                "nota": r[1],
                "texto": r[2],
                "feedback": r[3]
            })
            
        return jsonify({
            "status": "sucesso",
            "media_simulado": media_simulado,
            "historico_redacoes": historico_redacoes
        })
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

    
@app.route('/api/temas', methods=['GET'])
def obter_temas_redacao():
    """Busca os temas de redação direto no banco de dados de forma simplificada e dinâmica"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS temas_redacao (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(255) NOT NULL UNIQUE,
                textos_motivadores TEXT NOT NULL
            );
        """)
        conn.commit()

        # ✅ ALINHAMENTO CIRÚRGICO DA VALIDAÇÃO E INSERÇÃO DOS NOVOS TEMAS
        cur.execute("SELECT COUNT(*) FROM temas_redacao;")
        if cur.fetchone()[0] < 5:
            cur.execute("""
                INSERT INTO temas_redacao (titulo, textos_motivadores) VALUES 
                ('O impacto da inteligência artificial na educação do século XXI', 'Texto 1: A tecnologia avança rápido... Texto 2: Dados mostram que o uso de ferramentas de IA cresceu 40% nas escolas...'),
                ('Caminhos para combater a evasão escolar no Brasil contemporâneo', 'Texto 1: A pandemia intensificou a saída de jovens... Texto 2: O principal fator é a necessidade de trabalhar...'),
                ('Democratização do acesso ao cinema no Brasil', 'Texto 1: O cinema como ferramenta de inclusão... Texto 2: Grandes centros concentram a maioria das salas de exibição...'),
                ('Invisibilidade e registro civil: garantia de acesso à cidadania no Brasil', 'Texto 1: Milhares de brasileiros não possuem certidão de nascimento... Texto 2: Sem documento, o cidadão não existe para o Estado...'),
                ('Desafios para a valorização de comunidades e povos tradicionais no Brasil', 'Texto 1: A cultura indígena e quilombola enfrenta ameaças... Texto 2: A demarcação de terras e o respeito às tradições são garantias constitucionais...')
                ON CONFLICT (titulo) DO NOTHING;
            """)
            conn.commit()
            
        cur.execute("SELECT id, titulo, textos_motivadores FROM temas_redacao;")
        temas_banco = cur.fetchall()

        cur.close()
        conn.close()
        
        lista_temas = []
        for t in temas_banco:
            titulo_limpo = t[1].encode('utf-8', errors='ignore').decode('utf-8') if isinstance(t[1], str) else t[1]
            textos_limpos = t[2].encode('utf-8', errors='ignore').decode('utf-8') if isinstance(t[2], str) else t[2]
            
            lista_temas.append({
                "id": t[0],
                "titulo": titulo_limpo,
                "textos_motivadores": textos_limpos
            })
            
        return jsonify(lista_temas), 200

    except Exception as e:
        print(f"❌ ERRO CRÍTICO NA ROTA DE TEMAS: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/questoes/ia', methods=['POST'])
def obter_questoes_ia():
    """Gera questões inéditas E o conteúdo do edital baseado na banca informada"""
    dados = request.get_json()
    pesquisa_banca = dados.get('banca')

    if not pesquisa_banca:
        return jsonify({"status": "erro", "mensagem": "Nenhuma banca informada."}), 400

    prompt_sistema = "Você é um professor especialista em editais de concursos públicos e vestibulares brasileiros."
    prompt_usuario = f"""
    Com base na banca/concurso alvo '{pesquisa_banca}', faça duas coisas:
    1. Identifique as 3 matérias mais cobradas ou o núcleo do edital e dê um resumo cirúrgico (em tópicos) do que o aluno DEVE estudar.
    2. Gere um simulado contendo exatamente 5 questões inéditas de múltipla escolha focadas no perfil desse concurso.

    Retorne ESTRITAMENTE um objeto JSON puro, sem markdown (sem aspas ```json), seguindo EXATAMENTE esta estrutura:
    {{
      "edital_conteudo": "<h3>📚 Conteúdo Programático Sugerido (Foco no Edital)</h3><ul><li>Matéria 1: tópicos importantes...</li><li>Matéria 2: tópicos importantes...</li></ul>",
      "questoes": [
        {{
          "materia": "Nome da Disciplina",
          "enunciado": "Texto do enunciado da questão...",
          "opcoes": {{
            "A": "Texto da alternativa A",
            "B": "Texto da alternativa B",
            "C": "Texto da alternativa C",
            "D": "Texto da alternativa D",
            "E": "Texto da alternativa E"
          }},
          "correta": "A"
        }}
      ]
    }}
    """

    try:
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            temperature=0.5
        )
        
        texto_resposta = resposta.choices[0].message.content.strip()
        dados_gerados = json.loads(texto_resposta)
        return jsonify(dados_gerados), 200
        
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao gerar conteúdo e simulado por IA: {str(e)}"}), 500


@app.route('/api/redacao', methods=['POST'])
def corrigir_redacao():
    """Corrige a redação E gera um modelo de estrutura Nota 1000 focado no tema"""
    dados = request.get_json()
    if not dados:
        return jsonify({"status": "erro", "mensagem": "Dados não recebidos."}), 400

    texto_aluno = dados.get('texto')
    tema = dados.get('tema')
    usuario_id = dados.get('usuario_id')
    
    if not texto_aluno or not tema or not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    texto_aluno = texto_aluno.encode('utf-8', errors='ignore').decode('utf-8')
    tema = tema.encode('utf-8', errors='ignore').decode('utf-8')

    prompt_sistema = "Você é um corretor e redator nota 1000 especialista na prova de redação do ENEM."
    prompt_usuario = f"""
    Analise a redação abaixo e monte um esqueleto/modelo perfeito de redação Nota 1000 focado especificamente neste tema.
    
    TEMA: {tema}
    TEXTO DO ALUNO: {texto_aluno}
    
    Responda ESTRITAMENTE no formato JSON abaixo, mantendo as chaves exatas (em texto puro, sem aspas ```json):
    {{
      "nota": 820,
      "feedback": "Texto detalhado dividindo por competências...",
      "modelo_nota_1000": "<h3>🏗️ Modelo de Estrutura Nota 1000 - Tema: {tema}</h3><p><strong>Introdução:</strong> Aluda a um repertório... <strong>Desenvolvimento 1:</strong> Argumente sobre... <strong>Proposta de Intervenção:</strong> Agente + Ação + Meio + Detalhamento..."
    }}
    """

    try:
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            temperature=0.3
        )
        
        resposta_ia = resposta.choices[0].message.content.strip()
        print(f"DEBUG - Resposta Bruta da IA: {resposta_ia}")

        # 🛡️ FILTRO EXTRATOR AVANÇADO: Encontra o JSON mesmo se a IA colocar lixo ao redor
        start_idx = resposta_ia.find('{')
        end_idx = resposta_ia.rfind('}') + 1
        
        if start_idx != -1 and end_idx != 0:
            resposta_ia = resposta_ia[start_idx:end_idx]
        else:
            raise ValueError("A resposta da IA não contém um objeto JSON válido.")

        dados_correcao = json.loads(resposta_ia)

        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS redacoes (
                id SERIAL PRIMARY KEY,
                usuario_id INT REFERENCES usuarios(id) ON DELETE CASCADE,
                tema TEXT NOT NULL,
                texto TEXT NOT NULL,
                nota_final INT NOT NULL,
                feedback_ia TEXT NOT NULL,
                data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        cur.execute(
            "INSERT INTO redacoes (usuario_id, tema, texto, nota_final, feedback_ia) VALUES (%s, %s, %s, %s, %s);",
            (usuario_id, tema, texto_aluno, int(dados_correcao.get("nota", 700)), dados_correcao.get("feedback", ""))
        )
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "sucesso",
            "nota": dados_correcao.get("nota", 700),
            "feedback": dados_correcao.get("feedback", ""),
            "modelo_nota_1000": dados_correcao.get("modelo_nota_1000", "<h3>🏗️ Modelo</h3><p>Não gerado.</p>")
        }), 200

    except Exception as e:
        print(f"❌ ERRO CRÍTICO NA REDAÇÃO: {str(e)}")
        return jsonify({"status": "erro", "mensagem": f"Falha no processamento: {str(e)}"}), 500


@app.route('/api/sistema/status', methods=['GET'])
def status_sistema():
    """Verifica se o sistema precisa de atualização (expira em 2 dias)"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS controle_atualizacao (
                id SERIAL PRIMARY KEY,
                ultima_atualizacao TIMESTAMP NOT NULL
            );
        """)
        cur.execute("SELECT ultima_atualizacao FROM controle_atualizacao ORDER BY id DESC LIMIT 1;")
        resultado = cur.fetchone()
        
        if not resultado:
            cur.close()
            conn.close()
            return jsonify({"status": "desatualizado", "ultima": "Nunca"}), 200
            
        ultima_data = resultado[0]
        cur.close()
        conn.close()

        if datetime.now() - ultima_data > timedelta(days=2):
            return jsonify({"status": "desatualizado", "ultima": ultima_data.strftime('%d/%m/%Y %H:%M')}), 200
            
        return jsonify({"status": "atualizado", "ultima": ultima_data.strftime('%d/%m/%Y %H:%M')}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/sistema/atualizar', methods=['POST'])
def atualizar_sistema():
    """IA generates new general mock test packages to feed the cloud database"""
    try:
        prompt = """
        Gere 3 questões de múltipla escolha inéditas sendo: 1 de Matemática, 1 de Português e 1 de História.
        Retorne estritamente em formato JSON puro (um array de objetos), sem usar blocos de código markdown (não coloque ```json no início).
        Use a estrutura EXATA:
        [
          {"materia": "Matemática", "enunciado": "...", "opcoes": {"A": "..", "B": "..", "C": "..", "D": "..", "E": ".."}, "correta": "A"}
        ]
        """
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5
        )
        
        texto_resposta = resposta.choices[0].message.content.strip()
        if texto_resposta.startswith("```json"):
            texto_resposta = texto_resposta.replace("```json", "", 1)
        if texto_resposta.endswith("```"):
            texto_resposta = texto_resposta[:-3]
        texto_resposta = texto_resposta.strip()

        questoes = json.loads(texto_resposta)
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS questoes (
                id SERIAL PRIMARY KEY,
                materia VARCHAR(100) NOT NULL,
                enunciado TEXT NOT NULL,
                alternativa_a TEXT NOT NULL,
                alternativa_b TEXT NOT NULL,
                alternativa_c TEXT NOT NULL,
                alternativa_d TEXT NOT NULL,
                alternativa_e TEXT NOT NULL,
                resposta_correta VARCHAR(2) NOT NULL,
                data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        for q in questoes:
            opc = q.get('opcoes', {})
            alt_a = opc.get('A') or opc.get('a') or 'Alternativa A'
            alt_b = opc.get('B') or opc.get('b') or 'Alternativa B'
            alt_c = opc.get('C') or opc.get('c') or 'Alternativa C'
            alt_d = opc.get('D') or opc.get('d') or 'Alternativa D'
            alt_e = opc.get('E') or opc.get('e') or 'Alternativa E'
            correta = q.get('correta') or q.get('resposta_correta') or 'A'

            cur.execute(
                """INSERT INTO questoes (materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
                (q.get('materia', 'Geral'), q.get('enunciado'), alt_a, alt_b, alt_c, alt_d, alt_e, str(correta).upper())
            )
            
        cur.execute("INSERT INTO controle_atualizacao (ultima_atualizacao) VALUES (%s);", (datetime.now(),))
        conn.commit()
        cur.close()
        conn.close()
        
        print("🎉 Sincronização e carga de questões efetuadas com sucesso na Nuvem!")
        return jsonify({"status": "sucesso", "mensagem": "Banco de dados alimentado com sucesso!"}), 200

    except Exception as e:
        print(f"❌ ERRO CRÍTICO NA ATUALIZAÇÃO: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/insights', methods=['GET'])
def obter_insights():
    """Analisa o desempenho do usuário e gera dicas inteligentes personalizadas"""
    usuario_id = request.args.get('usuario_id')
    if not usuario_id:
        return jsonify({"status": "erro", "mensagem": "ID em falta"}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT materia, nota FROM simulados_realizados WHERE usuario_id = %s ORDER BY id DESC LIMIT 5;", (usuario_id,))
        historico = cur.fetchall()
        cur.close()
        conn.close()
        
        if not historico:
            return jsonify({"insight": "Realize seu primeiro simulado para a inteligência ativa analisar seus pontos fracos!"}), 200
            
        dados_estudo = ", ".join([f"Matéria: {h[0]} (Nota: {h[1]}%)" for h in historico])
        
        prompt = f"""
        Com base no seguinte histórico recente de simulados do aluno: [{dados_estudo}].
        Identifique a maior fraqueza dele e retorne uma única dica cirúrgica e motivadora de até 3 linhas de como ele pode melhorar essa matéria específica.
        """
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )
        
        return jsonify({"insight": resposta.choices[0].message.content.strip()}), 200
    except Exception as e:
        return jsonify({"insight": "Análise indisponível no momento."}), 200


@app.route('/api/gabarito/comentar', methods=['POST'])
def comentar_questao_ia():
    """Recebe uma questão e gera uma explicação pedagógica personalizada sobre o erro ou acerto"""
    dados = request.get_json()
    enunciado = dados.get('enunciado')
    opcoes = dados.get('opcoes')
    resposta_aluno = dados.get('resposta_aluno')
    resposta_correta = dados.get('resposta_correta')

    if not enunciado or not resposta_correta:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos para gerar comentário."}), 400

    prompt_sistema = "Você é um professor tutor altamente didático focado em sanar dúvidas de alunos para vestibulares e concursos."
    prompt_usuario = f"""
    O aluno respondeu a seguinte questão:
    Enunciado: {enunciado}
    Alternativas disponíveis: {json.dumps(opcoes, ensure_ascii=False)}
    
    O aluno marcou a alternativa: {resposta_aluno}
    O gabarito correto é a alternativa: {resposta_correta}
    
    Dê uma explicação cirúrgica, em no máximo 4 linhas, explicando por que a alternativa {resposta_correta} está correta e por que a resposta do aluno faz sentido ou onde ele se confundiu (caso ele tenha errado). Seja direto e use tom encorarador.
    """

    try:
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            temperature=0.5
        )
        
        comentario_ia = resposta.choices[0].message.content.strip()
        return jsonify({"status": "sucesso", "comentario": comentario_ia}), 200

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# ==========================================
# ROTAS DO SISTEMA DE LOGIN SOCIAL (GOOGLE OAuth)
# ==========================================

@app.route('/api/auth/google')
def login_google():
    """Redireciona o usuário para a tela de login do Google"""
    redirect_uri = request.args.get('redirect_uri')
    return google.authorize_redirect(redirect_uri)


@app.route('/api/auth/callback')
def auth_callback():
    """Recebe a resposta de sucesso do Google, cria ou loga o usuário no Postgres"""
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if not user_info:
            return "Erro ao obter dados do perfil do Google", 400
            
        email = user_info.get('email')
        nome = user_info.get('name')
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Garante a existência da tabela de usuários antes da checagem
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                nome VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL UNIQUE,
                senha VARCHAR(255) NOT NULL,
                data_cadastro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        
        # Verifica se o usuário já existe na sua tabela atual
        cur.execute("SELECT id, nome FROM usuarios WHERE email = %s;", (email,))
        usuario_existente = cur.fetchone()
        
        if usuario_existente:
            user_id = usuario_existente[0]
            user_nome = usuario_existente[1]
        else:
            # Se for o primeiro acesso, registra ele automaticamente no banco com uma senha aleatória estável
            senha_aleatoria = generate_password_hash(os.urandom(24).hex())
            cur.execute(
                "INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s) RETURNING id;",
                (nome, email, senha_aleatoria)
            )
            user_id = cur.fetchone()[0]
            user_nome = nome
            conn.commit()
            
        cur.close()
        conn.close()
        
        # Transmite os dados de login de volta para o seu Frontend via parâmetros na URL de sucesso
        frontend_url = "http://127.0.0.1:5500/frontend/index.html" 
        # 🌟 DETECÇÃO DINÂMICA DE URL (Evita o erro de Domains, protocols and ports must match)
        if os.environ.get("RENDER"):
            # Se estiver rodando no Render, redireciona para o seu site oficial no ar
            frontend_url = "https://estudo-intenso.onrender.com/index.html"
        else:
            # Se estiver rodando no seu computador (Local), usa a porta do seu Live Server
            frontend_url = "http://127.0.0.1:5500/frontend/index.html"
            
        return f"""
        <script>
            localStorage.setItem('usuario_estudo', JSON.stringify({{ id: {user_id}, nome: '{user_nome}' }}));
            window.location.href = '{frontend_url}';
        </script>
        """
    except Exception as e:
        print(f"❌ ERRO NO CALLBACK DO GOOGLE: {str(e)}")
        return f"Falha na autenticação: {str(e)}", 500


@app.route('/')
def home():
    return {"status": "online", "mensagem": "API do Estudo Intensivo operando com sucesso!"}, 200


if __name__ == '__main__':
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)