import { Drumstick, Wheat, Soup, Flame, ChefHat, Sunrise } from 'lucide-react';
import styles from './landing.module.css';

interface PopularDishesProps {
  onSelectDish: (name: string) => void;
}

const DISHES = [
  { name: 'Butter Chicken', tag: 'North Indian', Icon: Drumstick },
  { name: 'Matar Pulao', tag: 'Rice', Icon: Wheat },
  { name: 'Dal Makhani', tag: 'North Indian', Icon: Soup },
  { name: 'Paneer Tikka', tag: 'Starter', Icon: Flame },
  { name: 'Biryani', tag: 'Rice', Icon: ChefHat },
  { name: 'Poha', tag: 'Breakfast', Icon: Sunrise },
] as const;

// Ported from templates/index.html:1834-1880
export function PopularDishes({ onSelectDish }: PopularDishesProps) {
  return (
    <div className={styles.popularDishesSection}>
      <div className={styles.popularDishesLabel}>Popular right now</div>
      <div className={styles.popularDishesGrid}>
        {DISHES.map(({ name, tag, Icon }) => (
          <button
            key={name}
            type="button"
            className={styles.popularDishCard}
            onClick={() => onSelectDish(name)}
          >
            <div className={styles.popularDishIcon}>
              <Icon />
            </div>
            <div className={styles.popularDishInfo}>
              <span className={styles.popularDishName}>{name}</span>
              <span className={styles.popularDishTag}>{tag}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
