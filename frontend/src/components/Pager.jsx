export default function Pager({ page, setPage, count, size = 50 }) {
  const pages = Math.ceil(count / size) || 1;
  if (pages <= 1) return null;
  return (
    <div className="spread" style={{ marginTop: 16 }}>
      <span className="faint" style={{ fontSize: 13 }}>
        {count} total, page {page} of {pages}
      </span>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn-ghost" disabled={page <= 1}
                onClick={() => setPage(page - 1)}>Previous</button>
        <button className="btn-ghost" disabled={page >= pages}
                onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}
