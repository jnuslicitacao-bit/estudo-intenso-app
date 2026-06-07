import os
import json
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
    """Busca questões no banco de dados, permitindo filtrar por matéria de forma opcional"""
    materia_filtrada = request.args.get('materia') # Captura a matéria enviada na URL
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if materia_filtrada:
            # Busca apenas questões da matéria selecionada
            cur.execute(
                "SELECT id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e FROM questoes WHERE LOWER(materia) = LOWER(%s) LIMIT 10;",
                (materia_filtrada,)
            )
        else:
            # Se não passar matéria, traz de forma geral
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
    
@app.route('/api/temas', methods=['GET'])
def obtener_temas():
    """Busca temas de redação. Se o banco estiver vazio, popula automaticamente."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Garante a existência da tabela
        cur.execute("""
            CREATE TABLE IF NOT EXISTS temas_redacao (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(255) NOT NULL UNIQUE,
                textos_motivadores TEXT NOT NULL
            );
        """)
        conn.commit()

        cur.execute("SELECT id, titulo, textos_motivadores FROM temas_redacao;")
        temas_banco = cur.fetchall()

        # Se não houver temas, insere os padrões do ENEM/Concursos imediatamente
        if not temas_banco:
            temas_padrao = [
                ("O impacto da inteligência artificial na educação do século XXI", "Texto 1: A tecnologia avança rápido... Texto 2: Dados mostram que o uso de ferramentas de IA cresceu 40% nas escolas..."),
                ("Caminhos para combater a evasão escolar no Brasil contemporâneo", "Texto 1: A pandemia intensificou a saída de jovens... Texto 2: O principal fator é a necessidade de trabalhar...")
            ]
            for titulo, texto in temas_padrao:
                cur.execute("INSERT INTO temas_redacao (titulo, textos_motivadores) VALUES (%s, %s) ON CONFLICT DO NOTHING;", (titulo, texto))
            conn.commit()
            
            # Recarrega após inserir
            cur.execute("SELECT id, titulo, textos_motivadores FROM temas_redacao;")
            temas_banco = cur.fetchall()

        cur.close()
        conn.close()
        
        lista_temas = [{"id": t[0], "titulo": t[1], "textos_motivadores": t[2]} for t in temas_banco]
        return jsonify(lista_temas), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500
    
@app.route('/api/questoes/ia', methods=['POST'])
def obter_questoes_ia():
    """Gera questões inéditas simulando o estilo e o conteúdo de uma banca específica usando IA"""
    dados = request.get_json()
    pesquisa_banca = dados.get('banca')

    if not pesquisa_banca:
        return jsonify({"status": "erro", "mensagem": "Nenhuma banca informada."}), 400

    prompt_sistema = "Você é um professor especialista em bancas de concursos públicos e vestibulares brasileiros."
    prompt_usuario = f"""
    Gere um simulado contendo exatamente 5 questões inéditas de múltipla escolha focadas estritamente no perfil, conteúdo programático e nível de dificuldade da seguinte banca/concurso: {pesquisa_banca}.
    
    As matérias devem ser relevantes para esse concurso. As alternativas corretas devem ser distribuídas aleatoriamente.
    
    Retorne ESTRITAMENTE um array em formato JSON puro, sem comentários, sem markdown (sem aspas ```json no início ou fim), seguindo EXATAMENTE a estrutura deste exemplo:
    [
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
        
        # Converte a string JSON da IA em um objeto Python real
        questoes_geradas = json.loads(texto_resposta)
        
        return jsonify(questoes_geradas), 200
        
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao gerar questões por IA: {str(e)}"}), 500

from datetime import datetime, timedelta

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
            # Nunca atualizado
            return jsonify({"status": "desatualizado", "ultima": "Nunca"}), 200
            
        ultima_data = resultado[0]
        # Se a última atualização foi há mais de 48 horas, fica desatualizado
        if datetime.now() - ultima_data > timedelta(days=2):
            return jsonify({"status": "desatualizado", "ultima": ultima_data.strftime('%d/%m/%Y %H:%M')}), 200
            
        return jsonify({"status": "atualizado", "ultima": ultima_data.strftime('%d/%m/%Y %H:%M')}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/sistema/atualizar', methods=['POST'])
def atualizar_sistema():
    """IA gera novos pacotes de simulados gerais para alimentar o banco de dados"""
    try:
        prompt = """
        Gere 3 questões de múltipla escolha inéditas sendo: 1 de Matemática, 1 de Português e 1 de História.
        Retorne estritamente em formato JSON puro (array), sem markdown:
        [
          {"materia": "Matemática", "enunciado": "...", "opcoes": {"A": "..", "B": "..", "C": "..", "D": "..", "E": ".."}, "correta": "A"}
        ]
        """
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        questoes = json.loads(resposta.choices[0].message.content.strip())
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        for q in questoes:
            cur.execute(
                "INSERT INTO questoes (materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                (q['materia'], q['enunciado'], q['opcoes']['A'], q['opcoes']['B'], q['opcoes']['C'], q['opcoes']['D'], q['opcoes']['E'])
            )
            
        # Atualiza o timestamp de controle
        cur.execute("INSERT INTO controle_atualizacao (ultima_atualizacao) VALUES (%s);", (datetime.now(),))
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"status": "sucesso", "mensagem": "Banco de dados alimentado com sucesso!"}), 200
    except Exception as e:
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
        # Puxa os últimos simulados feitos pelo usuário
        cur.execute("SELECT materia, nota FROM simulados_historico WHERE usuario_id = %s ORDER BY id DESC LIMIT 5;", (usuario_id,))
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
        
        return jsonify({"insight": respuesta.choices[0].message.content.strip()}), 200
    except Exception as e:
        return jsonify({"insight": "Análise indisponível no momento."}), 200

if __name__ == '__main__':
    # Mantido desativado (debug=False) para evitar erros do Watchdog no Windows
    app.run(debug=False, port=5000)