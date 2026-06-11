import os
import json
import urllib.parse
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from openai import OpenAI
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth

# Adicione esta importação no topo do app.py
from gamificacao import calcular_patente, processar_xp_simulado, processar_xp_redacao, obter_feedback_militar

# 🌟 SÓ CARREGA O .ENV SE ESTIVER LOCALMENTE (Impede o bug de apagar as variáveis no Render)
if not os.environ.get("RENDER"):
    print("💻 Carregando variáveis do arquivo .env local...")
    load_dotenv()

app = Flask(__name__)
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
        return psycopg2.connect(database_url.strip())
    else:
        return psycopg2.connect(
            user="administrador",
            password="nova_senha123",
            host="localhost",
            port=5432,
            database="estudo_intensivo_db"
        )

def init_db():
    """Garante todas as tabelas e colunas alinhadas cirurgicamente no Postgres do Render"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Garante a tabela base de usuários
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

        # 2. Injeta colunas de gamificação na tabela de usuários de forma isolada
        colunas_usuarios = [
            ("xp", "INT DEFAULT 0"),
            ("patente", "VARCHAR(50) DEFAULT 'Recruta'"),
            ("streak_atual", "INT DEFAULT 0"),
            ("ultima_atividade", "DATE DEFAULT CURRENT_DATE")
        ]
        for nome_col, tipo_col in colunas_usuarios:
            try:
                cur.execute(f"ALTER TABLE usuarios ADD COLUMN {nome_col} {tipo_col};")
                conn.commit()
            except Exception:
                conn.rollback()

        # (Coloque este bloco logo após a criação da tabela conquistas_usuario)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS missoes_diarias (
                id SERIAL PRIMARY KEY,
                usuario_id INT REFERENCES usuarios(id) ON DELETE CASCADE,
                descricao VARCHAR(255) NOT NULL,
                xp_recompensa INT NOT NULL,
                concluida BOOLEAN DEFAULT FALSE,
                data_missao DATE DEFAULT CURRENT_DATE,
                UNIQUE(usuario_id, descricao, data_missao)
            );
        """)
        conn.commit()

        # 3. Garante a tabela de Simulados Realizados histórica
        cur.execute("""
            CREATE TABLE IF NOT EXISTS simulados_realizados (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                materia VARCHAR(100) NOT NULL,
                nota INT NOT NULL,
                data_realizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # 4. Garante a tabela de Redações com todas as colunas exigidas pelo SELECT
        cur.execute("""
            CREATE TABLE IF NOT EXISTS redacoes (
                id SERIAL PRIMARY KEY,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                tema TEXT NOT NULL,
                texto TEXT NOT NULL,
                nota_final INT NOT NULL,
                feedback_ia TEXT NOT NULL,
                data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()

        # 5. Garante a existência da coluna data_envio caso a tabela redacoes seja legada antiga
        try:
            cur.execute("ALTER TABLE redacoes ADD COLUMN data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP;")
            conn.commit()
        except Exception:
            conn.rollback()

        # 6. Garante o restante das tabelas do ecossistema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS conquistas_usuario (
                id SERIAL PRIMARY KEY,
                usuario_id INT REFERENCES usuarios(id) ON DELETE CASCADE,
                titulo_conquista VARCHAR(100) NOT NULL,
                descricao TEXT,
                data_ganha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(usuario_id, titulo_conquista)
            );
            CREATE TABLE IF NOT EXISTS controle_atualizacao (
                id SERIAL PRIMARY KEY,
                ultima_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        
        cur.close()
        conn.close()
        print("✅ [DATABASE] Varredura completa! Todas as tabelas e colunas estão operacionais.")
    except Exception as e:
        print(f"❌ [DATABASE ERROR]: {str(e)}")

# Executa fora do bloco __main__ para garantir a inicialização correta via WSGI/Gunicorn no Render
init_db()


# ==========================================
# ROTAS DE AUTENTICAÇÃO (LOGIN E CADASTRO)
# ==========================================

@app.route('/api/cadastro', methods=['POST'])
def cadastrar_usuario():
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"status": "erro", "mensagem": "Requisição inválida. Envie dados em formato JSON."}), 400
            
        nome = dados.get('nome')
        email = dados.get('email')
        senha = dados.get('senha')

        if not nome or not email or not senha:
            return jsonify({"status": "erro", "mensagem": "Por favor, preencha todos os campos obrigatórios."}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id FROM usuarios WHERE email = %s;", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            return jsonify({"status": "erro", "mensagem": "Este e-mail já está sendo utilizado por outro estudante."}), 400

        senha_criptografada = generate_password_hash(senha)
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s);",
            (nome, email, senha_criptografada)
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "sucesso", "mensagem": "Conta criada com sucesso!"}), 201

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro interno no servidor: {str(e)}"}), 500


@app.route('/api/login', methods=['POST'])
def login_usuario():
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

        if not usuario_encontrado or not check_password_hash(usuario_encontrado[2], senha):
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha incorretos."}), 401

        return jsonify({
            "status": "sucesso",
            "usuario": {
                "id": usuario_encontrado[0],
                "nome": usuario_encontrado[1]
            }
        }), 200

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# ==========================================
# ROTAS DO SISTEMA DE SIMULADOS E REDAÇÃO
# ==========================================

@app.route('/api/questoes', methods=['GET'])
def obter_questoes():
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
        
        lista_questoes = [{
            "id": q[0], 
            "materia": q[1], 
            "enunciado": q[2],
            "opcoes": {"A": q[3], "B": q[4], "C": q[5], "D": q[6], "E": q[7]}
        } for q in questoes]
        return jsonify(lista_questoes), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/simulado/salvar', methods=['POST'])
def salvar_simulado():
    try:
        dados = request.get_json()
        usuario_id = dados.get('usuario_id')
        materia = dados.get('materia', 'Geral')
        nota = dados.get('nota', 0)
        tempo_rapido = dados.get('completou_rapido', False)

        if not usuario_id:
            return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM simulados_realizados WHERE usuario_id = %s AND data_realizacao::DATE = CURRENT_DATE;", (usuario_id,))
        primeiro_do_dia = cur.fetchone()[0] == 0

        xp_ganho, medalhas = processar_xp_simulado(nota, tempo_rapido, primeiro_do_dia)

        cur.execute(
            "INSERT INTO simulados_realizados (usuario_id, materia, nota) VALUES (%s, %s, %s);",
            (usuario_id, materia, nota)
        )

        promocao = False
        nova_patente = "Recruta"
        if xp_ganho > 0:
            cur.execute("UPDATE usuarios SET xp = xp + %s WHERE id = %s RETURNING xp, patente;", (xp_ganho, usuario_id))
            usuario_atualizado = cur.fetchone()
            novo_xp, patente_antiga = usuario_atualizado[0], usuario_atualizado[1]
            
            nova_patente = calcular_patente(novo_xp)
            if nova_patente != patente_antiga:
                cur.execute("UPDATE usuarios SET patente = %s WHERE id = %s;", (nova_patente, usuario_id))
                promocao = True

            for medalha in medalhas:
                cur.execute("INSERT INTO conquistas_usuario (usuario_id, titulo_conquista) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (usuario_id, medalha))

        cur.execute("UPDATE usuarios SET streak_atual = streak_atual + 1, ultima_atividade = CURRENT_DATE WHERE id = %s;", (usuario_id,))
        
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "sucesso",
            "xp_ganho": xp_ganho,
            "promocao": promocao,
            "nova_patente": nova_patente,
            "feedback_ia": obter_feedback_militar(nota, "simulado")
        }), 201
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/simulados/historico', methods=['GET'])
def obter_historico_simulados():
    try:
        usuario_id = request.args.get('usuario_id')
        if not usuario_id:
            return jsonify({"status": "erro", "mensagem": "ID do usuário é obrigatório."}), 400

        conn = get_db_connection()
        cur = conn.cursor()
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

        historico = [{"materia": r[0], "nota": r[1]} for r in resultados]
        return jsonify(historico), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/desempenho', methods=['GET'])
def obter_desempenho():
    usuario_id = request.args.get('usuario_id')
    if not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT tema, nota_final, texto, feedback_ia FROM redacoes WHERE usuario_id = %s ORDER BY data_envio DESC LIMIT 5;", (usuario_id,))
        redacoes_banco = cur.fetchall()
        
        cur.execute("SELECT AVG(nota) FROM simulados_realizados WHERE usuario_id = %s;", (usuario_id,))
        resultado_media = cur.fetchone()[0]
        media_simulado = int(resultado_media) if resultado_media is not None else 0 

        cur.execute("SELECT COALESCE(xp, 0), COALESCE(patente, 'Recruta'), COALESCE(streak_atual, 0) FROM usuarios WHERE id = %s;", (usuario_id,))
        militar = cur.fetchone()

        cur.close()
        conn.close()
        
        xp_real = militar[0] if militar else 0
        patente_real = militar[1] if militar else "Recruta"
        streak_real = militar[2] if militar else 0

        historico_redacoes = [{
            "tema": r[0],
            "nota": r[1],
            "texto": r[2],
            "feedback": r[3]
        } for r in redacoes_banco]
            
        return jsonify({
            "status": "sucesso",
            "media_simulado": media_simulado,
            "historico_redacoes": historico_redacoes,
            "xp": xp_real,
            "patente": patente_real,
            "streak_atual": streak_real
        }), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

    
@app.route('/api/temas', methods=['GET'])
def obter_temas_redacao():
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
        
        lista_temas = [{
            "id": t[0],
            "titulo": t[1].encode('utf-8', errors='ignore').decode('utf-8') if isinstance(t[1], str) else t[1],
            "textos_motivadores": t[2].encode('utf-8', errors='ignore').decode('utf-8') if isinstance(t[2], str) else t[2]
        } for t in temas_banco]
            
        return jsonify(lista_temas), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/questoes/ia', methods=['POST'])
def obter_questoes_ia():
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
        return jsonify(json.loads(texto_resposta)), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao gerar conteúdo e simulado por IA: {str(e)}"}), 500


@app.route('/api/redacao', methods=['POST'])
def corrigir_redacao():
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

        start_idx = resposta_ia.find('{')
        end_idx = resposta_ia.rfind('}') + 1
        
        if start_idx != -1 and end_idx != 0:
            resposta_ia = resposta_ia[start_idx:end_idx]
        else:
            raise ValueError("A resposta da IA não contém um objeto JSON válido.")

        dados_correcao = json.loads(resposta_ia)
        nota_final = int(dados_correcao.get("nota", 700))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM redacoes WHERE usuario_id = %s AND nota_final >= 400 AND data_envio >= CURRENT_DATE - INTERVAL '7 days';", (usuario_id,))
        redacoes_na_semana = cur.fetchone()[0]
        
        xp_ganho, medalhas = processar_xp_redacao(nota_final, redacoes_na_semana + 1)

        cur.execute(
            "INSERT INTO redacoes (usuario_id, tema, texto, nota_final, feedback_ia) VALUES (%s, %s, %s, %s, %s);",
            (usuario_id, tema, texto_aluno, nota_final, dados_correcao.get("feedback", ""))
        )

        promocao = False
        nova_patente = "Recruta"
        if xp_ganho > 0:
            cur.execute("UPDATE usuarios SET xp = xp + %s WHERE id = %s RETURNING xp, patente;", (xp_ganho, usuario_id))
            u_atualizado = cur.fetchone()
            novo_xp, patente_antiga = u_atualizado[0], u_atualizado[1]
            
            nova_patente = calcular_patente(novo_xp)
            if nova_patente != patente_antiga:
                cur.execute("UPDATE usuarios SET patente = %s WHERE id = %s;", (nova_patente, usuario_id))
                promocao = True
                
            for medalha in medalhas:
                cur.execute("INSERT INTO conquistas_usuario (usuario_id, titulo_conquista) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (usuario_id, medalha))

        cur.execute("UPDATE usuarios SET streak_atual = streak_atual + 1, ultima_atividade = CURRENT_DATE WHERE id = %s;", (usuario_id,))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "sucesso",
            "nota": nota_final,
            "feedback": dados_correcao.get("feedback", ""),
            "modelo_nota_1000": dados_correcao.get("modelo_nota_1000", "<h3>🏗️ Modelo</h3><p>Não gerado.</p>"),
            "xp_ganho": xp_ganho,
            "promocao": promocao,
            "nova_patente": nova_patente,
            "feedback_militar": obter_feedback_militar(nota_final, "redacao")
        }), 200

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Falha no processamento: {str(e)}"}), 500


@app.route('/api/sistema/status', methods=['GET'])
def status_sistema():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
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
        
        return jsonify({"status": "sucesso", "mensagem": "Banco de dados alimentado com sucesso!"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/insights', methods=['GET'])
def obter_insights():
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
    
    Dê uma explicação cirúrgica, em no máximo 4 linhas, explicando por que a alternativa {resposta_correta} está correta e por que a resposta do aluno faz sentido ou onde ele se confundiu (caso ele tenha errado). Seja direto e use tom encorajador.
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
        return jsonify({"status": "sucesso", "comentario": resposta.choices[0].message.content.strip()}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# ==========================================
# ROTAS DO SISTEMA DE LOGIN SOCIAL (GOOGLE OAuth)
# ==========================================

@app.route('/api/auth/google')
def login_google():
    redirect_uri = request.args.get('redirect_uri')
    return google.authorize_redirect(redirect_uri)


@app.route('/api/auth/callback')
def auth_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            return "Erro ao obter dados do perfil do Google", 400
            
        email = user_info.get('email')
        nome = user_info.get('name')
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT id, nome FROM usuarios WHERE email = %s;", (email,))
        usuario_existente = cur.fetchone()
        
        if usuario_existente:
            user_id = usuario_existente[0]
            user_nome = usuario_existente[1]
        else:
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
        
        frontend_url = "https://estudo-intenso.onrender.com/index.html" if os.environ.get("RENDER") else "http://127.0.0.1:5500/frontend/index.html"
        nome_codificado = urllib.parse.quote(user_nome)
        
        return f"""
        <script>
            window.location.href = "{frontend_url}?id={user_id}&nome={nome_codificado}&social=true";
        </script>
        """
    except Exception as e:
        print(f"❌ ERRO NO CALLBACK DO GOOGLE: {str(e)}")
        return f"Falha na autenticação: {str(e)}", 500


@app.route('/api/ranking', methods=['GET'])
def obter_ranking():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(nome, 'Estudante Anônimo'), COALESCE(patente, 'Recruta'), COALESCE(xp, 0), COALESCE(streak_atual, 0) 
            FROM usuarios 
            WHERE nome IS NOT NULL
            ORDER BY COALESCE(xp, 0) DESC 
            LIMIT 10;
        """)
        usuarios_ranking = cur.fetchall()
        cur.close()
        conn.close()

        lista_ranking = [{
            "nome": u[0],
            "patente": u[1],
            "xp": u[2],
            "streak": u[3]
        } for u in usuarios_ranking]
        return jsonify(lista_ranking), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/')
def home():
    return {"status": "online", "mensagem": "API do Estudo Intensivo operando com sucesso!"}, 200

@app.route('/api/missoes', methods=['GET'])
def obter_missoes_diarias():
    """Busca ou gera as missões do dia para o soldado"""
    usuario_id = request.args.get('usuario_id')
    if not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Verifica se o usuário já tem missões geradas para a data de hoje
        cur.execute("""
            SELECT id, descricao, xp_recompensa, concluida 
            FROM missoes_diarias 
            WHERE usuario_id = %s AND data_missao = CURRENT_DATE;
        """, (usuario_id,))
        missoes = cur.fetchall()
        
        # 2. Se não tiver, o Estado-Maior designa 3 missões aleatórias para o dia dele
        if not missoes:
            pool_missoes = [
                ("Resolver 20 questões no simulado", 30),
                ("Concluir 1 simulado adaptativo", 50),
                ("Estudar por 1 hora no Modo Foco", 40),
                ("Submeter 1 redação para correção da IA", 100),
                ("Acertar mais de 70% em um caderno", 60)
            ]
            
            # Escolhe 3 missões aleatórias sem repetir
            import random
            missoes_do_dia = random.sample(pool_missoes, 3)
            
            for desc, xp in missoes_do_dia:
                try:
                    cur.execute("""
                        INSERT INTO missoes_diarias (usuario_id, descricao, xp_recompensa) 
                        VALUES (%s, %s, %s);
                    """, (usuario_id, desc, xp))
                except Exception:
                    conn.rollback()
            conn.commit()
            
            # Recarrega para trazer com os IDs certos do banco
            cur.execute("""
                SELECT id, descricao, xp_recompensa, concluida 
                FROM missoes_diarias 
                WHERE usuario_id = %s AND data_missao = CURRENT_DATE;
            """, (usuario_id,))
            missoes = cur.fetchall()
            
        cur.close()
        conn.close()
        
        lista_missoes = [{
            "id": m[0],
            "descricao": m[1],
            "xp": m[2],
            "concluida": m[3]
        } for m in missoes]
        
        return jsonify(lista_missoes), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


@app.route('/api/missoes/concluir', methods=['POST'])
def concluir_missao_diaria():
    """Marca uma missão como cumprida e injeta o XP na ficha do usuário"""
    dados = request.get_json()
    missao_id = dados.get('missao_id')
    usuario_id = dados.get('usuario_id')
    
    if not missao_id or not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Verifica se a missão já não foi concluída antes para evitar trapaças
        cur.execute("SELECT concluida, xp_recompensa, descricao FROM missoes_diarias WHERE id = %s AND usuario_id = %s;", (missao_id, usuario_id))
        registro = cur.fetchone()
        
        if not registro or registro[0] == True:
            cur.close()
            conn.close()
            return jsonify({"status": "erro", "mensagem": "Missão inválida ou já cumprida."}), 400
            
        xp_ganho = registro[1]
        
        # Atualiza o status da missão
        cur.execute("UPDATE missoes_diarias SET concluida = TRUE WHERE id = %s;", (missao_id,))
        
        # Bonifica o soldado com o XP da missão
        cur.execute("UPDATE usuarios SET xp = xp + %s WHERE id = %s RETURNING xp, patente;", (xp_ganho, usuario_id))
        usuario_atualizado = cur.fetchone()
        novo_xp, patente_antiga = usuario_atualizado[0], usuario_atualizado[1]
        
        # Verifica promoção
        nova_patente = calcular_patente(novo_xp)
        promocao = False
        if nova_patente != patente_antiga:
            cur.execute("UPDATE usuarios SET patente = %s WHERE id = %s;", (nova_patente, usuario_id))
            promocao = True
            
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "status": "sucesso",
            "xp_ganho": xp_ganho,
            "promocao": promocao,
            "nova_patente": nova_patente
        }), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/conquistas', methods=['GET'])
def obter_galeria_conquistas():
    """Retorna o catálogo completo de medalhas cruzado com as conquistas reais do soldado"""
    usuario_id = request.args.get('usuario_id')
    if not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400
        
    try:
        # Catálogo Oficial do Estado-Maior (Todas as conquistas disponíveis na plataforma)
        CATALOGO_MEDALHAS = [
            {"titulo": "Atirador de Elite", "descricao": "Alcançou 100% de acertos em qualquer simulado.", "icone": "🎯"},
            {"titulo": "Escritor de Ouro", "descricao": "Alcançou nota igual ou superior a 900 na Redação.", "icone": "🥇"},
            {"titulo": "Primeiro Sangue", "descricao": "Concluiu sua primeira atividade na plataforma.", "icone": "🩸"},
            {"titulo": "Constância Tática", "descricao": "Manteve uma sequência de estudos de 7 dias (Streak).", "icone": "🔥"},
            {"titulo": "Lenda Militar", "descricao": "Alcançou a marca histórica de 100 dias seguidos de estudo.", "icone": "👑"},
            {"titulo": "General Supremo", "descricao": "Chegou ao topo da carreira militar com 500.000 XP.", "icone": "🎖️"}
        ]

        conn = get_db_connection()
        cur = conn.cursor()
        
        # Busca apenas os títulos das medalhas que o usuário já desbloqueou de verdade
        cur.execute("SELECT titulo_conquista FROM conquistas_usuario WHERE usuario_id = %s;", (usuario_id,))
        desbloqueadas = [row[0] for row in cur.fetchall()]
        
        cur.close()
        conn.close()

        # Monta a resposta final anexando a flag 'desbloqueada' true ou false
        galeria_final = []
        for medalha in CATALOGO_MEDALHAS:
            galeria_final.append({
                "titulo": medalha["titulo"],
                "descricao": medalha["descricao"],
                "icone": medalha["icone"],
                "desbloqueada": medalha["titulo"] in desbloqueadas
            })

        return jsonify(galeria_final), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# ❌ ERRO COMUM: Não faça isso!
# if __name__ == '__main__':
#     app = Flask(__name__)  <-- O Gunicorn não lê aqui dentro!


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "uma_chave_secreta_muito_segura_123")
CORS(app)


if __name__ == '__main__':
    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta)