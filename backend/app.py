from flask import Flask, request, jsonify
from flask_cors import CORS
import pg8000.dbapi  # <-- Mudamos o driver aqui

app = Flask(__name__)
CORS(app)

def get_db_connection():
    # O pg8000 recebe os parâmetros diretamente e processa tudo em Python puro (UTF-8)
    conn = pg8000.dbapi.connect(
        host="localhost",
        database="estudo_intenso_db",
        user="postgres",            # Insira seu usuário real aqui
        password="nova_senha123" # Insira sua senha real aqui
    )
    return conn

@app.route('/api/questoes', methods=['GET'])
def obter_questoes():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Executa a busca das questões
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

@app.route('/api/redacao', methods=['POST'])
def corrigir_redacao():
    dados = request.get_json()
    texto_aluno = dados.get('texto')
    tema = dados.get('tema')
    
    nota_simulada = 840
    feedback_simulado = "Competência 1: Excelente vocabulário. Competência 5: Melhore a proposta de intervenção."

    conn = get_db_connection()
    cur = conn.cursor()
    
    # O pg8000 usa %s ou parâmetros normais para inserção de dados de forma segura
    cur.execute(
        "INSERT INTO redacoes (usuario_id, tema, texto, nota_final, feedback_ia) VALUES (%s, %s, %s, %s, %s);",
        (1, tema, texto_aluno, nota_simulada, feedback_simulado)
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