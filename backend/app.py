import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import pg8000.dbapi
from openai import OpenAI
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

app = Flask(__name__)
CORS(app)

# Busca a chave de API da OpenAI de forma segura no sistema operacional
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
    """Gerencia a conexão com o banco de dados PostgreSQL usando pg8000"""
    return pg8000.dbapi.connect(
        host="localhost",
        database="estudo_intenso_db",
        user="postgres",
        password="nova_senha123"  # Sua senha atualizada
    )

# ==========================================
# ROTAS DE AUTENTICAÇÃO (LOGIN E CADASTRO)
# ==========================================

@app.route('/api/cadastro', methods=['POST'])
def cadastrar_usuario():
    """Rota para registrar novos estudantes com senha criptografada"""
    dados = request.get_json()
    nome = dados.get('nome')
    email = dados.get('email')
    senha = dados.get('senha')

    if not nome or not email or not senha:
        return jsonify({"status": "erro", "mensagem": "Preencha todos os campos obrigatórios."}), 400

    senha_criptografada = generate_password_hash(senha)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO usuarios (nome, email, senha_hash) VALUES (%s, %s, %s) RETURNING id;",
            (nome, email, senha_criptografada)
        )
        usuario_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"status": "sucesso", "mensagem": "Usuário cadastrado com sucesso!", "usuario_id": usuario_id}), 201
    except Exception:
        return jsonify({"status": "erro", "mensagem": "Este e-mail já está cadastrado no sistema."}), 400

@app.route('/api/login', methods=['POST'])
def login_usuario():
    """Rota para validar o acesso do estudante"""
    dados = request.get_json()
    email = dados.get('email')
    senha = dados.get('senha')

    if not email or not senha:
        return jsonify({"status": "erro", "mensagem": "E-mail e senha são obrigatórios."}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nome, senha_hash FROM usuarios WHERE email = %s;", (email,))
    usuario = cur.fetchone()
    cur.close()
    conn.close()

    if usuario and check_password_hash(usuario[2], senha):
        return jsonify({
            "status": "sucesso",
            "usuario": {
                "id": usuario[0],
                "nome": usuario[1],
                "email": email
            }
        }), 200
    else:
        return jsonify({"status": "erro", "mensagem": "E-mail ou senha incorretos."}), 401


# ==========================================
# ROTAS DO SISTEMA DE SIMULADOS E REDAÇÃO
# ==========================================

@app.route('/api/questoes', methods=['GET'])
def obter_questoes():
    """Busca questões de fixação ativa no banco de dados para o simulado"""
    conn = get_db_connection()
    cur = conn.cursor()
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
    return jsonify(lista_questoes)

@app.route('/api/simulado/salvar', methods=['POST'])
def salvar_simulado():
    """Registra a pontuação real do estudante após concluir um simulado"""
    dados = request.get_json()
    usuario_id = dados.get('usuario_id')
    materia = dados.get('materia')
    nota = dados.get('nota')

    if not usuario_id or not materia or nota is None:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos para salvar."}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO simulados_historico (usuario_id, materia, nota) VALUES (%s, %s, %s);",
            (usuario_id, materia, nota)
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "sucesso", "mensagem": "Resultado do simulado salvo!"}), 201
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/redacao', methods=['POST'])
def corrigir_redacao():
    """Envia o texto para a OpenAI e vincula ao ID do usuário logado"""
    dados = request.get_json()
    texto_aluno = dados.get('texto')
    tema = dados.get('tema')
    usuario_id = dados.get('usuario_id')
    
    if not texto_aluno or not tema or not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    prompt_sistema = "Você é um corretor especialista em redações dissertativo-argumentativas no modelo do ENEM. Avalie com rigor."
    prompt_usuario = f"""
    Analise a redação abaixo com base no tema proposto.
    
    TEMA: {tema}
    TEXTO DO ALUNO:
    {texto_aluno}
    
    Responda ESTRITAMENTE no formato abaixo, sem saudações ou textos adicionais de introdução/conclusão:
    NOTA: [Insira aqui a nota final de 0 a 1000]
    ANÁLISE: [Insira aqui um feedback detalhado dividindo por pontos fortes, erros gramaticais encontrados e como melhorar a proposta de intervenção]
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
        
        resposta_ia = resposta.choices[0].message.content
        
        try:
            linhas = resposta_ia.split('\n')
            nota_final = int(linhas[0].replace('NOTA:', '').strip())
            feedback_real = resposta_ia.replace(linhas[0], '').replace('ANÁLISE:', '').strip()
        except Exception:
            nota_final = 740  
            feedback_real = resposta_ia

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO redacoes (usuario_id, tema, texto, nota_final, feedback_ia) VALUES (%s, %s, %s, %s, %s);",
            (usuario_id, tema, texto_aluno, nota_final, feedback_real)
        )
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "status": "sucesso",
            "nota": nota_final,
            "feedback": feedback_real
        })

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Falha na API da OpenAI: {str(e)}"}), 500

@app.route('/api/desempenho', methods=['GET'])
def obter_desempenho():
    """Busca métricas históricas filtrando pelo ID dinâmico do usuário logado"""
    usuario_id = request.args.get('usuario_id')
    
    if not usuario_id:
        return jsonify({"status": "erro", "mensagem": "Usuário não identificado."}), 400
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Puxa histórico completo incluindo o texto do aluno e o feedback da IA
        cur.execute("SELECT tema, nota_final, texto, feedback_ia FROM redacoes WHERE usuario_id = %s ORDER BY data_envio DESC LIMIT 5;", (usuario_id,))
        redacoes_banco = cur.fetchall()
        
        cur.execute("SELECT AVG(nota) FROM simulados_historico WHERE usuario_id = %s;", (usuario_id,))
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

if __name__ == '__main__':
    # Mantido desativado (debug=False) para evitar erros do Watchdog no Windows
    app.run(debug=False, port=5000)