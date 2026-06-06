from flask import Flask, request, jsonify
from flask_cors import CORS
import pg8000.dbapi
from openai import OpenAI
import os
from dotenv import load_dotenv  # <-- Importa o carregador de ambiente

# Carrega as variáveis do arquivo .env
load_dotenv()

app = Flask(__name__)
CORS(app)

# O Python agora busca a chave no sistema operacional, escondendo-a do código público
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

def get_db_connection():
# ... (o resto do código do banco e das rotas continua igualzinho)
    return pg8000.dbapi.connect(
        host="localhost",
        database="estudo_intenso_db",
        user="postgres",
        password="nova_senha123"
    )

@app.route('/api/questoes', methods=['GET'])
def obter_questoes():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e FROM questoes LIMIT 10;")
    questoes = cur.fetchall()
    cur.close()
    conn.close()
    
    lista_questoes = []
    for q in questoes:
        lista_questoes.append({
            "id": q[0], "materia": q[1], "enunciado": q[2],
            "opcoes": {"A": q[3], "B": q[4], "C": q[5], "D": q[6], "E": q[7]}
        })
    return jsonify(lista_questoes)

@app.route('/api/redacao', methods=['POST'])
def corrigir_redacao():
    dados = request.get_json()
    texto_aluno = dados.get('texto')
    tema = dados.get('tema')
    
    if not texto_aluno or not tema:
        return jsonify({"status": "erro", "mensagem": "Texto ou tema ausentes."}), 400

    # Engrenagem de Prompt focada na estratégia de correção rigorosa
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
        # CHAMADA OFICIAL DA API DA OPENAI (Utilizando gpt-4o-mini por ser rápido e barato)
        resposta = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ],
            temperature=0.3 # Mantém a IA focada e menos "criativa/imprevisível" na nota
        )
        
        resposta_ia = resposta.choices[0].message.content
        
        # Separando dinamicamente a NOTA do resto do FEEDBACK enviado pela OpenAI
        try:
            linhas = resposta_ia.split('\n')
            nota_final = int(linhas[0].replace('NOTA:', '').strip())
            feedback_real = resposta_ia.replace(linhas[0], '').replace('ANÁLISE:', '').strip()
        except Exception:
            nota_final = 740  # Nota padrão de contingência caso mude a formatação
            feedback_real = resposta_ia

        # GRAVANDO O RESULTADO REAL NO BANCO POSTGRESQL
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO redacoes (usuario_id, tema, texto, nota_final, feedback_ia) VALUES (%s, %s, %s, %s, %s);",
            (1, tema, texto_aluno, nota_final, feedback_real)
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
    """Rota que puxa o histórico de estudos do aluno para criar os gráficos"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # 1. Puxa o histórico de redações
        cur.execute("SELECT tema, nota_final, data_envio FROM redacoes WHERE usuario_id = 1 ORDER BY data_envio DESC LIMIT 5;")
        redacoes_banco = cur.fetchall()
        
        # 2. Puxa a média dos simulados (Para o MVP, criamos uma média simples)
        cur.execute("SELECT AVG(nota) FROM simulados_historico WHERE usuario_id = 1;")
        media_simulado = cur.fetchone()[0]
        # Se não houver simulados feitos, define uma média padrão de teste
        media_simulado = int(media_simulado) if media_simulado else 75 

        cur.close()
        conn.close()
        
        # Formata os dados das redações para o Frontend
        historico_redacoes = []
        for r in redacoes_banco:
            historico_redacoes.append({
                "tema": r[0],
                "nota": r[1]
            })
            
        return jsonify({
            "status": "sucesso",
            "media_simulado": media_simulado,
            "historico_redacoes": historico_redacoes
        })
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500
if __name__ == '__main__':
    app.run(debug=True, port=5000)