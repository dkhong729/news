export default function InsightCard({ item }) {
  return (
    <article className="card">
      <div className="cardHeader">
        <span className="badge">{item.category === 'ai_tech' ? 'AI Tech' : 'Product & Biz'}</span>
        <span className="score">Score {item.final_score?.toFixed?.(1) ?? item.final_score}</span>
      </div>
      <h3>{item.title}</h3>
      <p className="summary">{item.summary}</p>
      <p className="why">Why it matters: {item.why_it_matters}</p>
      <a className="source" href={item.url} target="_blank" rel="noreferrer">
        View source
      </a>
    </article>
  );
}
