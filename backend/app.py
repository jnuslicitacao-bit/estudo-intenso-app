from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2

app = Flask(__name__)
CORS(app) # Permite que o Frontend acesse o Backend

# Configuração da conexão com o PostgreSQL
def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        database="estudo_intenso_db",
        user="seu_usuario_postgres",
        password="sua_senha_postgres"
    )
    return conn

@app.route('/api/questoes', methods=['GET'])
def obter_questoes():
    """Rota que busca as questões do banco de dados para o simulado"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e FROM questoes LIMIT 10;")
    questoes = cur.fetchall()
    cur.close()
    conn.close()
    
    # Formata o retorno para o Frontend
    lista_questoes = []
    for q in questoes:
        lista_questoes.append({
            "id": q[0], "materia": q[1], "enunciado": q[2],
            "opcoes": {"A": q[3], "B": q[4], "C": q[5], "D": q[6], "E": q[7]}
        })
    return jsonify(lista_questoes)

@app.route('/api/redacao', methods=['POST'])
def corrigir_redacao():
    """Rota que recebe a redação do aluno e simula o retorno da correção por IA"""
    dados = request.get_json()
    texto_aluno = dados.get('texto')
    tema = dados.get('tema')
    
    # Aqui entraria a chamada de API da OpenAI/Gemini. 
    # Para o MVP, simulamos a resposta da IA:
    nota_simulada = 840
    feedback_simulado = "Competência 1: Excelente vocabulário. Competência 5: Melhore a proposta de intervenção."

    # Salva no Banco de Dados PostgreSQL
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO redacoes (usuario_id, tema, texto, nota_final, feedback_ia) VALUES (%s, %s, %s, %s, %s);",
        (1, tema, texto_aluno, nota_simulada, feedback_simulado) # Usando usuario_id=1 de teste
    )
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "status": "sucesso",
        "nota": nota_simulada,
        "feedback": feedback_simulado
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)